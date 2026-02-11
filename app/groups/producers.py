# groups/producers.py
"""
Activity producers for ownership change events.

Fires notifications to all active group owners when ownership
requests are created, canceled, executed, or fail.
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
