# atrium/tasks.py
#
# Celery tasks for the Atrium surface.
# keeper_compact_task — Continuous Keeper: summarize recent AtriumSessionEntry
# rows and store the result in ApertureLog.compact_summary.

import logging
import subprocess
import os

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

        # K-4: submit a proactive finding to Clio's registry (store-and-defer,
        # see keeper-adr-status.md — not surfaced anywhere yet, but this gives
        # K-3's storage its first real production caller).
        try:
            from clio import services as clio_services

            clio_services.submit_finding(
                keeper_id=f"continuous-keeper.{session_id}",
                finding_type="compact_summary_updated",
                finding_body={"session_id": session_id, "summary_chars": len(summary)},
                suggested_clio_signal="notice",
            )
        except Exception as exc:
            logger.warning("[keeper] Clio finding submission failed for session %s: %s", session_id, exc)

    except Exception as exc:
        logger.exception("[keeper] keeper_compact_task failed for session %s", session_id)
        raise self.retry(exc=exc, countdown=60)


def _run_claude_p(prompt: str) -> str | None:
    """
    Run a one-shot `claude -p` summarization call and return the text output.
    Uses the same API-key-stripped env as the main session subprocess.
    """
    from django.conf import settings
    from claude.service import _claude_bin, _strip_api_key

    bin_path = _claude_bin()
    cwd = getattr(settings, "ATRIUM_CLAUDE_CODE_CWD", "") or os.getcwd()

    try:
        result = subprocess.run(
            [bin_path, "-p", "--dangerously-skip-permissions", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd,
            env=_strip_api_key(os.environ.copy()),
        )
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            logger.warning("[keeper] claude -p exited %d stderr=%s", result.returncode, result.stderr[:200])
            return None
        return output
    except subprocess.TimeoutExpired:
        logger.warning("[keeper] claude -p timed out for summarization")
        return None
    except Exception as exc:
        logger.warning("[keeper] _run_claude_p failed: %s", exc)
        return None
