# scrap/signals.py
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _ingest_scrap(scrap):
    """Ingest a Scrap into Stackroom IR. No-op if Stackroom is unavailable."""
    try:
        from inkwell.tasks.stackroom_integration import ingest_object_task
        weight = 0.3 if scrap.status == "raw" else 1.0
        ingest_object_task.delay(
            app_label="scrap",
            model_name="Scrap",
            object_id=str(scrap.pk),
            weight=weight,
        )
    except Exception:
        pass


def _check_raw_pile(scrap):
    """CountNagKeeper instance (K-6, AD-8) — nag if this owner's raw pile crossed threshold."""
    try:
        from scrap.tasks import ensure_and_check_raw_scrap_pile
        ensure_and_check_raw_scrap_pile(scrap.content_type_id, scrap.owner_object_id)
    except Exception:
        logger.warning("[count-nag-keeper] raw pile check failed to dispatch", exc_info=True)


@receiver(post_save, sender="scrap.Scrap")
def on_scrap_save(sender, instance, created, **kwargs):
    if created:
        _ingest_scrap(instance)
        if instance.status == "raw":
            _check_raw_pile(instance)
    elif instance.status in ("reviewed", "promoted") and not created:
        _ingest_scrap(instance)
