"""
initiatives/signals.py

Signal handlers for the Initiatives app.
Wired in initiatives/apps.py ready().
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="initiatives.Initiative")
def create_aperture_log_for_initiative(sender, instance, created, **kwargs):
    """
    WT-B5: Auto-create an ApertureLog whenever a new Initiative is created.
    Uses get_or_create so re-saves are safe.
    """
    if not created:
        return
    from initiatives.models import ApertureLog
    ApertureLog.objects.get_or_create(initiative=instance)


@receiver(post_save, sender="initiatives.Session")
def ledger_session_started(sender, instance, created, **kwargs):
    """
    WT-B7: Append a ledger entry when a Session is created.
    """
    if not created:
        return
    _append_ledger(
        initiative=instance.initiative,
        event_type="session_started",
        body=f"Session started: '{instance.intent or 'untitled'}'",
        data={"session_id": str(instance.id)},
    )


@receiver(post_save, sender="initiatives.ApertureLogEntry")
def schedule_handover_on_new_entry(sender, instance, created, **kwargs):
    """
    Trigger the lock-debounced handover_task whenever a new ApertureLogEntry is saved.
    Skips handoff entries — a fresh handoff clears the draft; no generation needed.
    """
    if not created:
        return
    from initiatives.models import ApertureLogEntryKind
    if instance.kind == ApertureLogEntryKind.HANDOFF:
        return
    from initiatives.tasks import handover_task
    handover_task.delay(str(instance.aperture_log_id))


@receiver(post_save, sender="initiatives.ActionRun")
def on_action_run_saved(sender, instance, created, **kwargs):
    if instance.status != "succeeded":
        return
    if instance.tool_name == "writing.synopsis_linkedin":
        _persist_synopsis_linkedin(instance)
    elif instance.tool_name == "writing.summarize":
        _persist_writing_piece_synopsis(instance)


def _persist_synopsis_linkedin(action_run):
    result = action_run.result_payload or {}
    piece_id = (action_run.request_payload or {}).get("piece_id")
    if not piece_id:
        logger.warning("synopsis_linkedin action_run=%s missing piece_id in request_payload", action_run.id)
        return
    try:
        from writing.models import WritingPiece
        from writing.synopsis_service import SynopsisGenerationService
        piece = WritingPiece.objects.select_related("synopsis").get(pk=piece_id)
        synopsis = getattr(piece, "synopsis", None)
        if synopsis is None:
            synopsis = SynopsisGenerationService.generate_for_piece(piece)
        if synopsis is None:
            logger.error("synopsis_linkedin could not bootstrap WritingSynopsis for piece %s", piece_id)
            return
        synopsis.linkedin_copy = result.get("short_synopsis") or result.get("hook", "")
        synopsis.linkedin_copy_generated_by = "ai"
        synopsis.linkedin_synopsis_confirmed = False
        synopsis.linkedin_copy_extended = {
            "hook": result.get("hook", ""),
            "short_synopsis": result.get("short_synopsis", ""),
            "one_line_takeaway": result.get("one_line_takeaway", ""),
            "alt_hook": result.get("alt_hook", ""),
            "source_claim": result.get("source_claim", ""),
            "human_stake": result.get("human_stake", ""),
            "action_run_id": str(action_run.id),
        }
        synopsis.save(
            update_fields=[
                "linkedin_copy",
                "linkedin_copy_generated_by",
                "linkedin_copy_extended",
                "linkedin_synopsis_confirmed",
                "updated_at",
            ]
        )
        logger.info("synopsis_linkedin persisted to WritingSynopsis piece=%s action_run=%s", piece_id, action_run.id)
    except Exception:
        logger.exception("synopsis_linkedin signal failed for piece=%s action_run=%s", piece_id, action_run.id)


def _persist_writing_piece_synopsis(action_run):
    result = action_run.result_payload or {}
    piece_id = (action_run.request_payload or {}).get("piece_id")
    summary = result.get("summary", "")
    if not piece_id or not summary:
        return
    try:
        from writing.models import WritingPiece
        from writing.synopsis_service import SynopsisGenerationService
        piece = WritingPiece.objects.select_related("synopsis").get(pk=piece_id)
        synopsis = getattr(piece, "synopsis", None)
        if synopsis is None:
            synopsis = SynopsisGenerationService.generate_for_piece(piece)
        if synopsis is None:
            logger.error("writing.summarize could not find WritingSynopsis for piece %s", piece_id)
            return
        synopsis.teaser = summary[:220]
        synopsis.description = summary[:500]
        synopsis.generated_by = "ai"
        synopsis.public_synopsis_confirmed = False
        synopsis.save(
            update_fields=[
                "teaser",
                "description",
                "generated_by",
                "public_synopsis_confirmed",
                "updated_at",
            ]
        )
        logger.info("writing.summarize persisted to WritingSynopsis piece=%s action_run=%s", piece_id, action_run.id)
    except Exception:
        logger.exception("writing.summarize signal failed for piece=%s action_run=%s", piece_id, action_run.id)


def _append_ledger(initiative, event_type: str, body: str, data: dict | None = None):
    """Create a ledger ApertureLogEntry for an initiative, auto-creating the ApertureLog if needed."""
    from initiatives.models import ApertureLog, ApertureLogEntry, ApertureLogEntryKind
    try:
        aperture_log, _ = ApertureLog.objects.get_or_create(initiative=initiative)
        ApertureLogEntry.objects.create(
            aperture_log=aperture_log,
            kind=ApertureLogEntryKind.LEDGER,
            ledger_event_type=event_type,
            body=body,
            ledger_data=data or {},
            is_system_generated=True,
            authored_by="system",
        )
    except Exception:
        pass  # ledger failures must never interrupt the triggering operation
