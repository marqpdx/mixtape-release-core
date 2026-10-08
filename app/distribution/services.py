# distribution/services.py
"""
Distribution execution service.

execute_publish_event()  — fire all source processors for a PublishEvent
create_publish_event()   — create a PublishEvent from a sources_config list
cancel_publish_event()   — cancel a pending scheduled event
"""

import logging

from django.db import transaction
from django.utils.timezone import now

logger = logging.getLogger(__name__)


def create_publish_event(*, piece, created_by, sources_config: list, scheduled_at=None):
    """
    Create a PublishEvent for a WritingPiece.

    Args:
        piece:          WritingPiece instance
        created_by:     User instance
        sources_config: list of {source_id: str, config: dict}
        scheduled_at:   datetime or None (None = execute immediately)

    Returns:
        PublishEvent instance (status=pending)
    """
    from .models import PublishEvent

    event = PublishEvent.objects.create(
        writing_piece=piece,
        created_by=created_by,
        sources_config=sources_config or [],
        scheduled_at=scheduled_at,
    )
    return event


@transaction.atomic
def execute_publish_event(event_id: str) -> None:
    """
    Execute a PublishEvent — fire all configured Source processors.

    Idempotent: if status is not 'pending', returns immediately.
    Each processor result produces one ShareRecord.
    Partial success is valid: a failed channel does not block others.
    """
    from .models import PublishEvent, PublishEventStatus, ShareRecord, Source
    from .processors.registry import get_processor

    try:
        event = PublishEvent.objects.select_for_update().get(id=event_id)
    except PublishEvent.DoesNotExist:
        logger.error("execute_publish_event: PublishEvent %s not found", event_id)
        return

    if event.status != PublishEventStatus.PENDING:
        logger.info(
            "execute_publish_event: skipping %s (status=%s)", event_id, event.status
        )
        return

    event.status = PublishEventStatus.EXECUTING
    event.save(update_fields=["status", "updated_at"])

    piece = event.writing_piece
    any_failure = False

    for source_cfg in (event.sources_config or []):
        source_id = source_cfg.get("source_id")
        config = source_cfg.get("config") or {}

        # Skip if ShareRecord already exists (idempotency)
        if ShareRecord.objects.filter(publish_event=event, source_id=source_id).exists():
            continue

        try:
            source = Source.objects.get(id=source_id)
        except Source.DoesNotExist:
            ShareRecord.objects.create(
                publish_event=event,
                source_id=source_id,
                status="skipped",
                failure_reason=f"Source {source_id} not found",
            )
            continue

        processor = get_processor(source.kind)
        if not processor:
            ShareRecord.objects.create(
                publish_event=event,
                source=source,
                status="skipped",
                failure_reason=f"No processor registered for kind '{source.kind}'",
            )
            continue

        try:
            result = processor.process(piece, source, config)
        except Exception as exc:
            logger.exception("Processor %s raised: %s", source.kind, exc)
            result = {
                "status": "failed",
                "canonical_url": "",
                "og_title": "",
                "synopsis": "",
                "og_image": "",
                "channel_config": config,
                "channel_response": {},
                "failure_reason": str(exc),
            }

        ShareRecord.objects.create(
            publish_event=event,
            source=source,
            status=result.get("status", "failed"),
            canonical_url=result.get("canonical_url", ""),
            og_title=result.get("og_title", ""),
            synopsis=result.get("synopsis", ""),
            og_image=result.get("og_image", ""),
            channel_config=result.get("channel_config", {}),
            channel_response=result.get("channel_response", {}),
            failure_reason=result.get("failure_reason", ""),
        )

        if result.get("status") == "failed":
            any_failure = True

    event.status = PublishEventStatus.FAILED if any_failure else PublishEventStatus.COMPLETED
    event.executed_at = now()
    event.save(update_fields=["status", "executed_at", "updated_at"])

    _notify_linkedin_ready(event)


def _notify_linkedin_ready(event) -> None:
    """
    After a PublishEvent completes, email the author if LinkedIn succeeded.
    The email includes the share URL and post copy so they can share in one click.
    Non-fatal: any exception is caught and logged.
    """
    try:
        from .models import ShareRecord

        record = ShareRecord.objects.filter(
            publish_event=event,
            source__kind="linkedin",
            status="success",
        ).select_related("publish_event__writing_piece__author").first()

        if not record:
            return

        piece = event.writing_piece
        author = piece.author
        if not getattr(author, "email", None):
            return

        share_url = record.channel_response.get("linkedin_share_url", "")
        post_copy = record.channel_response.get("post_copy", "")
        if not share_url:
            return

        from utils.tasks import send_transactional_email_task

        piece_url = record.canonical_url

        send_transactional_email_task.delay(
            subject=f'"{piece.title}" is live — share on LinkedIn',
            to_emails=[author.email],
            template_base="email/linkedin_share_ready",
            context={
                "piece_title": piece.title,
                "piece_url": piece_url,
                "post_copy": post_copy,
                "linkedin_share_url": share_url,
            },
        )
    except Exception as exc:
        logger.warning("_notify_linkedin_ready failed: %s", exc)


def schedule_publish_event(event) -> None:
    """
    Schedule a Celery task to execute the PublishEvent at event.scheduled_at.
    Sets event.celery_task_id.
    """
    from .tasks import execute_scheduled_publish_event

    task = execute_scheduled_publish_event.apply_async(
        args=[str(event.id)],
        eta=event.scheduled_at,
    )
    event.celery_task_id = task.id
    event.save(update_fields=["celery_task_id", "updated_at"])


def cancel_publish_event(event) -> bool:
    """
    Cancel a pending scheduled PublishEvent.
    Returns True if successfully cancelled, False if not cancellable.
    """
    from .models import PublishEventStatus

    if event.status != PublishEventStatus.PENDING:
        return False

    if event.celery_task_id:
        try:
            from celery.result import AsyncResult
            AsyncResult(event.celery_task_id).revoke(terminate=False)
        except Exception as exc:
            logger.warning("Failed to revoke Celery task %s: %s", event.celery_task_id, exc)

    event.status = PublishEventStatus.CANCELLED
    event.save(update_fields=["status", "updated_at"])
    return True
