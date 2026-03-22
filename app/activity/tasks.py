# activity/tasks.py celery fanout

from __future__ import annotations

import logging

import requests
from celery import shared_task
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from activity.models import Action, ActionOutbox, Notification
from activity.services.audience import resolve_audience
from activity.services.preferences import apply_preferences
from activity.services.utils import max_priority

logger = logging.getLogger(__name__)


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

    try:
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
                        level=level,
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
                            level=level,
                        )
                    # else: keep existing notif (represents the same object already)

            outbox.dispatched_at = timezone.now()
            outbox.attempts = models.F("attempts") + 1
            outbox.last_error = ""
            outbox.save(update_fields=["dispatched_at", "attempts", "last_error"])

            # Collect notification PKs for post-commit dispatch.
            # .delay() must NOT be called inside the transaction — the worker can
            # pick up the task before the commit lands, causing DoesNotExist on lookup.
            push_notif_pks = []
            socket_notif_pks = []

            if action.channel == "messages":
                for user in recipients:
                    notif = Notification.objects.filter(
                        recipient=user,
                        dedupe_key=action.dedupe_key,
                    ).first()
                    if notif:
                        push_notif_pks.append(str(notif.pk))

            if action.channel == "activity":
                for user in recipients:
                    notif = Notification.objects.filter(
                        recipient=user,
                        dedupe_key=action.dedupe_key,
                    ).first()
                    if notif:
                        socket_notif_pks.append(str(notif.pk))

        # Transaction committed — safe to enqueue downstream tasks now.
        for pk in push_notif_pks:
            dispatch_push_notification_task.delay(pk)
        for pk in socket_notif_pks:
            dispatch_socket_notification_task.delay(pk)

    except Exception as exc:
        ActionOutbox.objects.filter(action=action).update(
            attempts=models.F("attempts") + 1,
            last_error=str(exc),
        )
        raise


_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def dispatch_push_notification_task(self, notification_id: str):
    """
    Send a push notification for a single Notification row.

    - Loads the Notification and its metadata
    - Finds all active PushTokens for the recipient
    - POSTs to the Expo push API
    - Prunes tokens that Expo reports as DeviceNotRegistered
    - Logs success and failure
    """
    from users.models import PushToken

    try:
        notif = (
            Notification.objects
            .select_related("action", "recipient")
            .get(pk=notification_id)
        )
    except Notification.DoesNotExist:
        return

    if notif.level == "mute":
        return

    tokens = list(
        PushToken.objects.filter(
            user=notif.recipient,
            is_active=True,
            provider="expo",
        )
    )

    if not tokens:
        return

    metadata = getattr(notif.action, "metadata", {}) or {}
    title = metadata.get("conversation_title") or "New message"
    body = metadata.get("message_preview") or "You have a new message"
    conversation_slug = metadata.get("conversation_slug", "")

    messages = [
        {
            "to": t.token,
            "title": title,
            "body": body,
            "data": {
                "conversationId": conversation_slug,
                "title": title,
            },
            "channelId": "messages",
            "sound": "default",
        }
        for t in tokens
    ]

    try:
        resp = requests.post(
            _EXPO_PUSH_URL,
            json=messages,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])
    except Exception as exc:
        logger.error("push_dispatch_failed notification=%s error=%s", notification_id, exc)
        raise

    # Prune dead tokens
    token_map = {t.token: t for t in tokens}
    for item, token_obj in zip(results, tokens):
        status_val = item.get("status")
        details = item.get("details", {})
        if status_val == "ok":
            logger.info(
                "push_sent notification=%s token_prefix=%s",
                notification_id, token_obj.token[:12],
            )
        elif details.get("error") == "DeviceNotRegistered":
            logger.warning(
                "push_token_stale token_prefix=%s — deactivating",
                token_obj.token[:12],
            )
            PushToken.objects.filter(pk=token_obj.pk).update(is_active=False)
        else:
            logger.warning(
                "push_delivery_issue notification=%s token_prefix=%s status=%s details=%s",
                notification_id, token_obj.token[:12], status_val, details,
            )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def dispatch_socket_notification_task(self, notification_id: str):
    """
    Emit a real-time socket event to a recipient's connected browser tab(s)
    by POSTing to livewire's internal /notify endpoint.

    Used for activity-channel notifications (e.g., group broadcasts).
    """
    from django.conf import settings

    try:
        notif = (
            Notification.objects
            .select_related("action", "action__activity_type", "recipient")
            .get(pk=notification_id)
        )
    except Notification.DoesNotExist:
        return

    if notif.level == "mute":
        return

    username = notif.recipient.username
    metadata = getattr(notif.action, "metadata", {}) or {}
    activity_type = getattr(notif.action, "activity_type", None)
    code = activity_type.code if activity_type else ""

    payload = {
        "id": str(notif.pk),
        "code": code,
        "bucket": notif.bucket,
        "priority": notif.priority,
        "title": metadata.get("title", ""),
        "body": metadata.get("body", ""),
        "action_url": metadata.get("action_url", ""),
    }

    livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
    secret = getattr(settings, "LIVEWIRE_NOTIFY_SECRET", "")

    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Notify-Secret"] = secret

    try:
        resp = requests.post(
            f"{livewire_url}/notify",
            json={"event": "notification:new", "username": username, "payload": payload},
            headers=headers,
            timeout=5,
        )
        resp.raise_for_status()
        logger.info("socket_notification_sent notification=%s user=%s", notification_id, username)
    except Exception as exc:
        logger.warning("socket_notification_failed notification=%s error=%s", notification_id, exc)
        raise
