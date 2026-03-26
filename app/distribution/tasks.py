# distribution/tasks.py
"""
Celery tasks for deferred and recovery publishing.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils.timezone import now

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_scheduled_publish_event(self, event_id: str) -> None:
    """Execute a PublishEvent at its scheduled_at time."""
    try:
        from .services import execute_publish_event
        execute_publish_event(event_id)
    except Exception as exc:
        logger.exception("execute_scheduled_publish_event failed for %s: %s", event_id, exc)
        raise self.retry(exc=exc, countdown=60)


@shared_task
def recover_missed_publish_events() -> None:
    """
    Beat safeguard: find pending scheduled events that should have fired
    (missed due to worker restart or downtime) and execute them.
    Runs every 5 minutes via beat schedule.
    """
    from .models import PublishEvent, PublishEventStatus

    cutoff = now() - timedelta(minutes=2)
    missed = PublishEvent.objects.filter(
        status=PublishEventStatus.PENDING,
        scheduled_at__lte=cutoff,
    )
    for event in missed:
        logger.info("recover_missed_publish_events: recovering event %s", event.id)
        execute_scheduled_publish_event.delay(str(event.id))
