# recurring_action/tasks.py
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    name="recurring_action.tasks.advance_recurring_actions",
    bind=True,
    max_retries=0,
    ignore_result=True,
)
def advance_recurring_actions(self):
    """
    Beat-scheduled task (every 15 minutes).
    Advances next_due_at for all active RecurringActions that are past due.
    Advances from previous next_due_at (not from now) to preserve cadence.
    """
    from .models import RecurringAction, RecurrencePattern

    INTERVALS = {
        RecurrencePattern.DAILY:    timedelta(days=1),
        RecurrencePattern.WEEKLY:   timedelta(weeks=1),
        RecurrencePattern.BIWEEKLY: timedelta(weeks=2),
        RecurrencePattern.MONTHLY:  timedelta(days=30),
    }

    now = timezone.now()
    due = RecurringAction.objects.filter(is_active=True, next_due_at__lte=now)
    count = 0
    for action in due:
        interval = INTERVALS.get(action.recurrence_rule)
        if interval is None:
            logger.warning(
                "Unknown recurrence_rule %r on RecurringAction %s",
                action.recurrence_rule,
                action.pk,
            )
            continue
        action.last_triggered_at = now
        action.next_due_at = action.next_due_at + interval
        action.save(update_fields=["last_triggered_at", "next_due_at", "updated_at"])
        count += 1
    logger.info("advance_recurring_actions: advanced %d actions", count)
