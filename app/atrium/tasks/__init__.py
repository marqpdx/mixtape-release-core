# atrium/tasks.py
#
# Celery tasks for the Atrium surface. All three run on the runtime worker, on the
# Dialogue owner's own account (ST-3 Part B), never on the server's login:
#   run_dialogue_turn   — write one agent reply in a Dialogue (atrium/turns.py)
#   run_distill         — produce a Distillate from a Dialogue
#   run_compact         — write a checkpoint entry: the Dialogue so far, summarized
#   keeper_compact_task — Continuous Keeper: summarize a Dialogue into its
#                         InitiativeLog's compact_summary

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

_DISTILL_PROMPT_TEMPLATE = """\
You are a knowledge distiller. The following is a transcript of an AI-assisted \
work session titled "{title}". Produce a {document_type_label} document with \
the title "{title}".

Guidelines for a {document_type_label}:
{document_type_guidance}

Session transcript:
{transcript}

Write only the document body — no title heading, no preamble. Use markdown.
"""

_MAX_TRANSCRIPT_CHARS = 40_000  # trim if very long

_CHECKPOINT_PROMPT_TEMPLATE = """\
The following is an Atrium Dialogue between a Person and one or more AI agents \
(each line is labelled with who said it). Write a checkpoint: a summary that lets \
any agent carry on the Dialogue without the transcript. Keep the decisions made, \
what was agreed and what was rejected, named files, documents and concepts, open \
questions, and where the work is heading. Be specific; use short paragraphs or bullets.

Transcript:
{transcript}

Write only the checkpoint, no preamble.
"""


@shared_task(name="atrium.tasks.run_dialogue_turn", queue="runtime", soft_time_limit=420, time_limit=480)
def run_dialogue_turn(entry_id: str) -> str:
    from atrium.turns import run_turn

    return run_turn(entry_id)


@shared_task(name="atrium.tasks.run_compact", queue="runtime", soft_time_limit=240, time_limit=300)
def run_compact(entry_id: str) -> str:
    """Fill a pending checkpoint entry, on the owner's own Claude account (ST-3 Part B step 4)."""
    from atrium import relay
    from atrium.ai.service import build_transcript
    from atrium.models import DialogueEntry, DialogueEntryStatus
    from atrium.turns import TurnStop, _fail_entry, run_once

    try:
        entry = DialogueEntry.objects.select_related("dialogue", "dialogue__member").get(pk=entry_id)
    except DialogueEntry.DoesNotExist:
        return "missing"
    if entry.status != DialogueEntryStatus.PENDING:
        return entry.status

    entry.status = DialogueEntryStatus.STREAMING
    entry.save(update_fields=["status", "updated_at"])
    relay.notify(entry.id)
    transcript = build_transcript(
        entry.dialogue, _MAX_TRANSCRIPT_CHARS, since_checkpoint=True, before=entry.created_at
    )
    try:
        entry.content = run_once(entry.dialogue, _CHECKPOINT_PROMPT_TEMPLATE.format(transcript=transcript)).strip()
    except TurnStop as stop:
        logger.warning("[atrium] compact %s stopped: %s", entry_id, stop.code)
        _fail_entry(entry, stop.code)
        return "failed"
    entry.status = DialogueEntryStatus.DONE
    entry.error_code = ""
    entry.save(update_fields=["content", "status", "error_code", "updated_at"])
    relay.notify(entry.id)
    return "done"


@shared_task(name="atrium.tasks.run_distill", queue="runtime", soft_time_limit=240, time_limit=300)
def run_distill(distillate_id: str) -> str:
    """Fill a pending Distillate from its Dialogue, on the owner's own Claude account."""
    from atrium.ai.service import build_transcript
    from atrium.distill import DOCUMENT_TYPE_GUIDANCE
    from atrium.models import Distillate, DistillateDocumentType, DistillateStatus
    from atrium.turns import TurnStop, run_once

    try:
        distillate = Distillate.objects.select_related("dialogue", "dialogue__member").get(pk=distillate_id)
    except Distillate.DoesNotExist:
        return "missing"
    if distillate.status != DistillateStatus.PENDING or distillate.dialogue is None:
        return distillate.status

    transcript = build_transcript(distillate.dialogue, _MAX_TRANSCRIPT_CHARS)
    label = dict(DistillateDocumentType.choices).get(distillate.document_type, distillate.document_type)
    prompt = _DISTILL_PROMPT_TEMPLATE.format(
        title=distillate.title,
        document_type_label=label,
        document_type_guidance=DOCUMENT_TYPE_GUIDANCE.get(
            distillate.document_type, DOCUMENT_TYPE_GUIDANCE[DistillateDocumentType.OTHER]
        ),
        transcript=transcript,
    )
    try:
        distillate.body = run_once(distillate.dialogue, prompt)
        distillate.status = DistillateStatus.DONE
        distillate.error_code = ""
    except TurnStop as stop:
        logger.warning("[atrium] distill %s stopped: %s", distillate_id, stop.code)
        distillate.status = DistillateStatus.FAILED
        distillate.error_code = stop.code
    distillate.save(update_fields=["body", "status", "error_code"])
    return distillate.status


@shared_task(bind=True, max_retries=2, queue="runtime")
def keeper_compact_task(self, session_id: str) -> None:
    """
    Continuous Keeper: summarize a Dialogue and store the result in its
    InitiativeLog's compact_summary. `session_id` is the Dialogue's id (the
    keeper's instance parameters keep that name).

    Runs on the Dialogue owner's own Claude account. When the account can't run
    (none, signed out, not allowed), the summary waits for the next trigger: no
    retry, and never the server's login.
    """
    try:
        from atrium.ai.service import _resolve_initiative_log, build_transcript
        from atrium.models import Dialogue
        from atrium.turns import TurnStop, run_once

        try:
            dialogue = Dialogue.objects.select_related("member").get(id=session_id, deleted_at__isnull=True)
        except Dialogue.DoesNotExist:
            logger.warning("[keeper] Dialogue not found: %s", session_id)
            return

        log, cadence = _resolve_initiative_log(dialogue)
        if log is None:
            logger.warning("[keeper] no InitiativeLog for Dialogue %s", session_id)
            return

        transcript = build_transcript(dialogue, _MAX_TRANSCRIPT_CHARS)
        if not transcript:
            return

        try:
            summary = run_once(dialogue, _SUMMARIZE_PROMPT_TEMPLATE.format(transcript=transcript), timeout=120)
        except TurnStop as stop:
            logger.info("[keeper] summary for Dialogue %s skipped: %s", session_id, stop.code)
            return

        from django.utils import timezone
        log.compact_summary = summary
        log.compact_at = timezone.now()
        log.save(update_fields=["compact_summary", "compact_at"])
        logger.info("[keeper] compact summary updated for Dialogue %s (%d chars)", session_id, len(summary))

        # K-4: submit a proactive finding to Clio's registry. As of CLIO-1b
        # (2026-09-28), sponsored by the Dialogue's member, so it can surface
        # through that member's ClioState feed (notice tier).
        try:
            from django.contrib.contenttypes.models import ContentType

            from clio import services as clio_services

            profile_ct_id = ContentType.objects.get_for_model(type(dialogue.member)).id
            clio_services.submit_finding(
                keeper_id=f"continuous-keeper.{session_id}",
                finding_type="compact_summary_updated",
                finding_body={
                    "session_id": session_id,
                    "summary_chars": len(summary),
                    "message": "Your Atrium Dialogue summary was updated.",
                },
                suggested_clio_signal="notice",
                sponsor_content_type_id=profile_ct_id,
                sponsor_object_id=dialogue.member_id,
            )
        except Exception as exc:
            logger.warning("[keeper] Clio finding submission failed for Dialogue %s: %s", session_id, exc)

    except Exception as exc:
        logger.exception("[keeper] keeper_compact_task failed for Dialogue %s", session_id)
        raise self.retry(exc=exc, countdown=60)
