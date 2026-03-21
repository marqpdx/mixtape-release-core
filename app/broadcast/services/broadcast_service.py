# broadcast/services/broadcast_service.py
"""
Core broadcast service.

send_broadcast(broadcast) — the single entry point for dispatching a GroupBroadcast.
Called immediately for unscheduled broadcasts (on status → queued) and by the
Celery beat task for scheduled ones.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from broadcast.models import BroadcastDelivery, GroupBroadcast, UserBroadcastPreferences

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def send_broadcast(broadcast: GroupBroadcast) -> None:
    """
    Resolve audience, apply preferences, fan out across configured channels.

    In-app: creates Action + ActionOutbox → existing fanout_action_task pipeline.
    Email:  enqueues dispatch_broadcast_email_task → Listmonk campaign per broadcast.
    SMS:    logs deferred, no dispatch.
    """
    recipients = _resolve_recipients(broadcast)

    if not recipients:
        logger.info("broadcast_no_recipients broadcast=%s — marking sent", broadcast.pk)
        _mark_sent(broadcast)
        return

    channels = broadcast.channels or []

    if "in_app" in channels:
        in_app_recipients = [u for u in recipients if _user_allows(u, broadcast.group, "in_app")]
        if in_app_recipients:
            _fanout_in_app(broadcast, in_app_recipients)
            BroadcastDelivery.objects.bulk_create(
                [
                    BroadcastDelivery(
                        broadcast=broadcast,
                        user=u,
                        channel=BroadcastDelivery.Channel.IN_APP,
                        status=BroadcastDelivery.DeliveryStatus.SENT,
                        sent_at=timezone.now(),
                    )
                    for u in in_app_recipients
                ],
                ignore_conflicts=True,
            )
            logger.info(
                "broadcast_in_app_fanned_out broadcast=%s recipients=%d",
                broadcast.pk, len(in_app_recipients),
            )

    if "email" in channels:
        from broadcast.tasks import dispatch_broadcast_email_task

        dispatch_broadcast_email_task.delay(str(broadcast.pk))
        logger.info("broadcast_email_enqueued broadcast=%s", broadcast.pk)

    if "sms" in channels:
        logger.info(
            "broadcast_sms_deferred broadcast=%s — SMS channel not yet implemented (Phase 2)",
            broadcast.pk,
        )

    _mark_sent(broadcast)


# ---------------------------------------------------------------------------
# Audience resolution
# ---------------------------------------------------------------------------

def _resolve_recipients(broadcast: GroupBroadcast) -> list:
    """Expand BroadcastAudience into a deduplicated list of active Users."""
    from groups.models import GroupMembership

    audience = broadcast.audiences.first()
    if not audience:
        return []

    scope = audience.scope_type
    # GroupMembership uses a GFK for member (member_content_type / member_object_id),
    # so we can't traverse it via User queryset filter. Query memberships directly.
    user_ct = ContentType.objects.get_for_model(User)

    if scope == "all_members":
        user_ids = list(
            GroupMembership.objects.filter(
                group=broadcast.group,
                member_content_type=user_ct,
                deleted_at__isnull=True,
            ).values_list("member_object_id", flat=True)
        )
        users = list(User.objects.filter(pk__in=user_ids, is_active=True))

    elif scope == "role":
        if not audience.role:
            return []
        user_ids = list(
            GroupMembership.objects.filter(
                group=broadcast.group,
                member_content_type=user_ct,
                roles__contains=[audience.role],
                deleted_at__isnull=True,
            ).values_list("member_object_id", flat=True)
        )
        users = list(User.objects.filter(pk__in=user_ids, is_active=True))

    elif scope == "custom":
        users = list(
            User.objects.filter(
                pk__in=audience.user_ids,
                is_active=True,
            )
        )

    else:
        users = []

    return users


# ---------------------------------------------------------------------------
# Preference check
# ---------------------------------------------------------------------------

def _user_allows(user, group, channel: str) -> bool:
    """
    Return True if the user wants to receive this channel for this group.
    Group-specific pref takes precedence over global default.
    Built-in defaults: in_app=True, email=False, sms=False.
    """
    pref = (
        UserBroadcastPreferences.objects.filter(user=user, group=group).first()
        or UserBroadcastPreferences.objects.filter(user=user, group__isnull=True).first()
    )

    if pref is None:
        return channel == "in_app"

    if channel == "in_app":
        return pref.allow_in_app
    if channel == "email":
        return pref.allow_email
    # SMS always false in Phase 1 regardless of stored value
    return False


# ---------------------------------------------------------------------------
# In-app fan-out via existing activity pipeline
# ---------------------------------------------------------------------------

def _fanout_in_app(broadcast: GroupBroadcast, recipients: list) -> None:
    """
    Create Action + ActionOutbox to fan out through the existing activity pipeline.
    The fanout_action_task will create one Notification per recipient.
    """
    from activity.models import Action, ActionOutbox, ActivityType
    from activity.services.validation import validate_audience_spec

    at, _ = ActivityType.objects.get_or_create(
        code="group.broadcast",
        defaults=dict(
            title="Group Broadcast",
            summary="A steward-authored message to group members.",
            default_channel="activity",
            default_priority="normal",
            suppressible_by_user=True,
        ),
    )

    # Map broadcast priority → activity priority
    priority = "critical" if broadcast.priority == "urgent" else "normal"

    audience_spec = {
        "type": "users",
        "ids": [str(u.pk) for u in recipients],
        "exclude_actor": False,
    }
    validate_audience_spec(audience_spec)

    broadcast_ct = ContentType.objects.get_for_model(GroupBroadcast)
    group_ct = ContentType.objects.get_for_model(broadcast.group.__class__)
    user_ct = ContentType.objects.get_for_model(broadcast.created_by.__class__)

    action = Action.objects.create(
        actor_content_type=user_ct,
        actor_id=str(broadcast.created_by_id),
        actor_label="user",
        object_content_type=broadcast_ct,
        object_id=str(broadcast.pk),
        context_content_type=group_ct,
        context_id=str(broadcast.group_id),
        activity_type=at,
        verb="broadcast",
        activity_code=at.code,
        channel="activity",
        priority=priority,
        metadata={
            "title": broadcast.title,
            "body": broadcast.body[:200],   # used by dispatch_socket_notification_task
            "group_slug": broadcast.group.slug,
            "group_title": str(getattr(broadcast.group, "title", "")),
            "broadcast_priority": broadcast.priority,
        },
        # Each broadcast gets its own dedupe key (no rollup across broadcasts)
        dedupe_key=f"group.broadcast:{broadcast.pk}",
        aggregate_key=f"group-broadcasts:{broadcast.group_id}",
        audience=audience_spec,
        occurs_at=timezone.now(),
    )
    ActionOutbox.objects.create(action=action)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark_sent(broadcast: GroupBroadcast) -> None:
    GroupBroadcast.objects.filter(pk=broadcast.pk).update(
        status=GroupBroadcast.Status.SENT,
        sent_at=timezone.now(),
    )
