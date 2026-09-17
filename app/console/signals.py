import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="console.HubCapture")
def on_hub_capture_save(sender, instance, created, update_fields, **kwargs):
    """
    InboxKeeper (K-7) — advisory content-type guess on newly-landed
    captures. Fires when: (a) a text capture is created directly with a
    body already set (status OPEN), or (b) an audio capture transitions
    PROCESSING -> OPEN once transcribe_hub_capture_task finishes (detected
    via update_fields, since that task's .save() always passes it).
    """
    from console.models import HubCaptureStatus

    is_new_open_capture = created and instance.status == HubCaptureStatus.OPEN
    is_transcription_complete = (
        not created
        and instance.status == HubCaptureStatus.OPEN
        and update_fields is not None
        and "status" in update_fields
    )
    if is_new_open_capture or is_transcription_complete:
        try:
            from console.inbox_keeper import check_and_submit_guess
            check_and_submit_guess(instance)
        except Exception:
            logger.warning("[inbox-keeper] failed to dispatch guess for capture %s", instance.id, exc_info=True)


# Known signal marker types surfaced on the Console.
# raw_name values match what WritingMarkerOccurrence.raw_name stores after
# the regex detects /! /~ /? /@ in piece bodies.

SIGNAL_MARKER_REGISTRY = {
    "!": {
        "slug": "important",
        "label": "Important",
        "inverse_label": "Marked as important",
        "symbol": "/!",
    },
    "~": {
        "slug": "inprogress",
        "label": "In Progress",
        "inverse_label": "In motion",
        "symbol": "/~",
    },
    "?": {
        "slug": "question",
        "label": "Open Questions",
        "inverse_label": "Uncertain",
        "symbol": "/?",
    },
    "@": {
        "slug": "delegated",
        "label": "Waiting / Delegated",
        "inverse_label": "Delegating to",
        "symbol": "/@",
    },
}

SIGNAL_MARKER_NAMES = list(SIGNAL_MARKER_REGISTRY.keys())
