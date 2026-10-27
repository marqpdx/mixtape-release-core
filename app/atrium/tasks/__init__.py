# atrium/tasks.py
#
# Celery tasks for the Atrium surface.
# keeper_compact_task — Continuous Keeper: summarize recent AtriumSessionEntry
# rows and store the result in ApertureLog.compact_summary.

import logging

from celery import shared_task

from atrium.tasks import keepers  # noqa: F401 — registers RecencyKeeper tasks (K-5)

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT_TEMPLATE = """\
You are a session summarizer. The following is a transcript of an AI-assisted \
work session. Summarize it in 2-4 paragraphs, capturing: key decisions made, \
specific artifacts or documents discussed, open questions, and the current \
direction of work. Be specific — name files, features, and concepts by their \
actual names. This summary will be injected as context in the next session.

Transcript:
{transcript}

Write only the summary, no preamble.
"""

_MAX_TRANSCRIPT_CHARS = 40_000  # trim if very long


@shared_task(bind=True, max_retries=2, queue="catalyst")
def keeper_compact_task(self, session_id: str) -> None:
    """
    Continuous Keeper: summarize recent AtriumSessionEntry records for a session
    and store the result in ApertureLog.compact_summary.

    Uses a one-shot `claude -p` subprocess — distinct from the live session
    subprocess, so it does not interfere with in-progress exchanges.
    """
    try:
        from atrium.models import AtriumSession, AtriumSessionEntry, AtriumSessionRole
        from atrium.ai.service import _resolve_aperture_log

        try:
            session = AtriumSession.objects.get(id=session_id, deleted_at__isnull=True)
        except AtriumSession.DoesNotExist:
            logger.warning("[keeper] session not found: %s", session_id)
            return

        log, cadence = _resolve_aperture_log(session)
        if log is None:
            logger.warning("[keeper] no ApertureLog for session %s", session_id)
            return

        entries = list(
            AtriumSessionEntry.objects.filter(session=session).order_by("created_at")
        )
        if not entries:
            return

        lines = []
        for entry in entries:
            role_label = "User" if entry.role == AtriumSessionRole.USER else "Assistant"
            lines.append(f"{role_label}: {entry.content.strip()}")
        transcript = "\n".join(lines)
        if len(transcript) > _MAX_TRANSCRIPT_CHARS:
            transcript = transcript[-_MAX_TRANSCRIPT_CHARS:]

        prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(transcript=transcript)
        summary = _run_claude_p(prompt)
        if not summary:
            logger.warning("[keeper] empty summary for session %s", session_id)
            return

        from django.utils import timezone
        log.compact_summary = summary
        log.compact_at = timezone.now()
        log.save(update_fields=["compact_summary", "compact_at"])
        logger.info("[keeper] compact summary updated for session %s (%d chars)", session_id, len(summary))

        # K-4: submit a proactive finding to Clio's registry. As of CLIO-1b
        # (2026-09-28), sponsored by the session's member, so it can surface
        # through that member's ClioState feed (notice tier).
        try:
            from django.contrib.contenttypes.models import ContentType

            from clio import services as clio_services

            profile_ct_id = ContentType.objects.get_for_model(type(session.member)).id
            clio_services.submit_finding(
                keeper_id=f"continuous-keeper.{session_id}",
                finding_type="compact_summary_updated",
                finding_body={
                    "session_id": session_id,
                    "summary_chars": len(summary),
                    "message": "Your Atrium session summary was updated.",
                },
                suggested_clio_signal="notice",
                sponsor_content_type_id=profile_ct_id,
                sponsor_object_id=session.member_id,
            )
        except Exception as exc:
            logger.warning("[keeper] Clio finding submission failed for session %s: %s", session_id, exc)

    except Exception as exc:
        logger.exception("[keeper] keeper_compact_task failed for session %s", session_id)
        raise self.retry(exc=exc, countdown=60)


def _run_claude_p(prompt: str) -> str | None:
    """
    Run a one-shot `claude -p` summarization call and return the text output.
    Goes through the shared runner: no tools, an empty scratch directory,
    and the API key stripped (ST-2).
    """
    from claude.service import NO_TOOLS, run_blocking

    result = run_blocking(prompt, timeout=120, tools=NO_TOOLS, log_context={"phase": "keeper-summary"})
    if result.failure:
        logger.warning("[keeper] claude -p summarization failed: %s", result.failure)
        return None
    return result.output
