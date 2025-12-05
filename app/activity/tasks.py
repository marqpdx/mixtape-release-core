# activity/tasks.py celery fanout

from __future__ import annotations

from celery import shared_task
from django.db import models, transaction
from django.utils import timezone

from activity.models import Action, ActionOutbox, Notification
from activity.services.audience import resolve_audience
from activity.services.preferences import apply_preferences
from activity.services.utils import max_priority


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def fanout_action_task(self, action_id: str):
    """
    Idempotent fanout:
      - Resolve audience
      - Apply user preferences (mute/digest/realtime)
      - Upsert Notification per recipient by (recipient, dedupe_key)
      - Roll up aggregate_count when aggregate_key matches
    """
    try:
        action = (Action.objects
                  .select_related("activity_type")
                  .get(pk=action_id))
    except Action.DoesNotExist:
        return

    recipients = resolve_audience(action.audience, action)

    # For visibility: if action is clearly not for notifications (e.g., plain chat message), skip
    # In your producers, avoid creating Action for routine chat messages.

    with transaction.atomic():
        outbox = ActionOutbox.objects.select_for_update().get(action=action)
        # If already dispatched, we can be idempotent; but still attempt fanout (e.g., partial failures)
        for user in recipients:
            level, bucket, priority = apply_preferences(user, action)
            if level == "mute":
                continue

            notif, created = Notification.objects.get_or_create(
                recipient=user,
                dedupe_key=action.dedupe_key,
                defaults=dict(
                    action=action,
                    bucket=bucket,
                    priority=priority,
                    aggregate_key=action.aggregate_key,
                    last_occurred_at=action.occurs_at,
                ),
            )
            if not created:
                # Only roll up when the aggregate_key matches (same rolling topic)
                if notif.aggregate_key == action.aggregate_key:
                    Notification.objects.filter(pk=notif.pk).update(
                        aggregate_count=models.F("aggregate_count") + 1,
                        last_occurred_at=action.occurs_at,
                        priority=max_priority(notif.priority, priority),
                    )
                # else: keep existing notif (represents the same object already)

        outbox.dispatched_at = timezone.now()
        outbox.attempts = models.F("attempts") + 1
        outbox.save(update_fields=["dispatched_at", "attempts"])
