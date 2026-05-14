# inkwell/stackroom_enqueue.py
#
# Public entry points for enqueueing Stackroom ingest/deactivation.
# Call these from post_save signals via transaction.on_commit.

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import transaction


def enqueue_stackroom_ingest(obj, *, reason: str = "auto") -> None:
    """Enqueue async Stackroom ingest for obj after the current transaction commits."""
    ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)

    def _enqueue():
        from inkwell.tasks.stackroom_integration import ingest_object_task
        ingest_object_task.apply_async(
            kwargs={
                "content_type_id": ct.pk,
                "object_id": str(obj.pk),
                "reason": reason,
            },
            queue="commons",
        )

    transaction.on_commit(_enqueue)


def enqueue_stackroom_deactivate(obj, *, reason: str = "deleted") -> None:
    """Enqueue async Stackroom deactivation for obj after the current transaction commits."""
    ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)

    def _enqueue():
        from inkwell.tasks.stackroom_integration import deactivate_object_task
        deactivate_object_task.apply_async(
            kwargs={
                "content_type_id": ct.pk,
                "object_id": str(obj.pk),
                "reason": reason,
            },
            queue="commons",
        )

    transaction.on_commit(_enqueue)
