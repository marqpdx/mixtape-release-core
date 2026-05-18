"""
initiatives/signals.py

Signal handlers for the Initiatives app.
Wired in initiatives/apps.py ready().
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


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
