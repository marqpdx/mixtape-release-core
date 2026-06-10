# groups/producers.py

"""
Activity producers for group events.

- Ownership change events → notify owners
- Join/request events → notify admins and stewards
"""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def _owner_user_ids(group) -> list[str]:
    """Get IDs of all active owners in a group."""
    from groups.services.ownership import get_active_owners
    return [str(m.member_object_id) for m in get_active_owners(group)]


def _moderator_user_ids(group) -> list[str]:
    """Get IDs of all active admins and stewards in a group."""
    from django.contrib.auth import get_user_model
    from django.contrib.contenttypes.models import ContentType
    from groups.models.membership import GroupMembership

    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    memberships = GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        is_active=True,
        is_banned=False,
        is_evicted=False,
    )
    ids = []
    for m in memberships:
        if m.is_admin() or m.is_steward() or m.is_owner():
            ids.append(str(m.member_object_id))
    return ids


def on_ownership_change_requested(*, request, group):
    at = _ensure_activity_type(
        code="group.ownership.requested",
        label="Ownership Change Requested",
        default_channel="system",
        default_priority="critical",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(request.requested_by),
        actor_id=_id(request.requested_by),
        actor_label="user",
        object_content_type=_ct(request),
        object_id=_id(request),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="requested",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "action": request.action,
            "target_user_id": str(request.target_user_id),
            "execute_after": request.execute_after.isoformat(),
        },
        dedupe_key=f"{at.code}:{_id(request)}",
        aggregate_key=f"ownership:{_id(group)}",
        audience={
            "type": "users",
            "ids": _owner_user_ids(group),
            "exclude_actor": False,
        },
        occurs_at=timezone.now(),
    )


def on_ownership_change_canceled(*, request, group):
    at = _ensure_activity_type(
        code="group.ownership.canceled",
        label="Ownership Change Canceled",
        default_channel="system",
        default_priority="critical",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(request.canceled_by),
        actor_id=_id(request.canceled_by),
        actor_label="user",
        object_content_type=_ct(request),
        object_id=_id(request),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="canceled",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "action": request.action,
            "target_user_id": str(request.target_user_id),
        },
        dedupe_key=f"{at.code}:{_id(request)}",
        aggregate_key=f"ownership:{_id(group)}",
        audience={
            "type": "users",
            "ids": _owner_user_ids(group),
            "exclude_actor": False,
        },
        occurs_at=timezone.now(),
    )


def on_ownership_change_executed(*, request, group):
    at = _ensure_activity_type(
        code="group.ownership.executed",
        label="Ownership Change Executed",
        default_channel="system",
        default_priority="critical",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(group),
        actor_id=_id(group),
        actor_label="system",
        object_content_type=_ct(request),
        object_id=_id(request),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="executed",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "action": request.action,
            "target_user_id": str(request.target_user_id),
        },
        dedupe_key=f"{at.code}:{_id(request)}",
        aggregate_key=f"ownership:{_id(group)}",
        audience={
            "type": "users",
            "ids": _owner_user_ids(group),
            "exclude_actor": False,
        },
        occurs_at=timezone.now(),
    )


def on_ownership_change_failed(*, request, group):
    at = _ensure_activity_type(
        code="group.ownership.failed",
        label="Ownership Change Failed",
        default_channel="system",
        default_priority="critical",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(group),
        actor_id=_id(group),
        actor_label="system",
        object_content_type=_ct(request),
        object_id=_id(request),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="failed",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "action": request.action,
            "target_user_id": str(request.target_user_id),
            "failure_reason": request.failure_reason,
        },
        dedupe_key=f"{at.code}:{_id(request)}",
        aggregate_key=f"ownership:{_id(group)}",
        audience={
            "type": "users",
            "ids": _owner_user_ids(group),
            "exclude_actor": False,
        },
        occurs_at=timezone.now(),
    )


# ============================================================================
# Join / Request-to-Join Events
# ============================================================================

def on_member_joined(*, user, group, membership):
    """Notify group moderators when a user directly joins."""
    moderator_ids = _moderator_user_ids(group)
    if not moderator_ids:
        return
    at = _ensure_activity_type(
        code="group.member.joined",
        label="Member Joined Group",
        default_channel="system",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(user),
        actor_id=_id(user),
        actor_label="user",
        object_content_type=_ct(membership),
        object_id=_id(membership),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="joined",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "username": user.username,
        },
        dedupe_key=f"{at.code}:{_id(user)}:{_id(group)}",
        aggregate_key=f"membership:{_id(group)}",
        audience={
            "type": "users",
            "ids": moderator_ids,
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )


def on_join_request_submitted(*, user, group, invitation):
    """Notify group moderators when a user requests to join."""
    moderator_ids = _moderator_user_ids(group)
    if not moderator_ids:
        return
    at = _ensure_activity_type(
        code="group.join_request.submitted",
        label="Join Request Submitted",
        default_channel="system",
        default_priority="high",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(user),
        actor_id=_id(user),
        actor_label="user",
        object_content_type=_ct(invitation),
        object_id=_id(invitation),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="requested_to_join",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "username": user.username,
            "message": invitation.message or "",
        },
        dedupe_key=f"{at.code}:{_id(invitation)}",
        aggregate_key=f"join_requests:{_id(group)}",
        audience={
            "type": "users",
            "ids": moderator_ids,
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )


def on_join_request_responded(*, responder, user, group, invitation, action):
    """Notify the requesting user when their join request is accepted or declined."""
    at = _ensure_activity_type(
        code=f"group.join_request.{action}",
        label=f"Join Request {'Accepted' if action == 'accept' else 'Declined'}",
        default_channel="system",
        default_priority="high",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(responder),
        actor_id=_id(responder),
        actor_label="user",
        object_content_type=_ct(invitation),
        object_id=_id(invitation),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb=action,
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "action": action,
        },
        dedupe_key=f"{at.code}:{_id(invitation)}",
        aggregate_key=f"join_requests:{_id(group)}",
        audience={
            "type": "users",
            "ids": [str(_id(user))],
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )
