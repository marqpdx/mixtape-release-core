# activity/producers_livewire.py
"""Activity producers for group-scoped Livewire (chat) events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_group_chat_message(*, message, conversation, group):
    """Notify group members when a message is sent in a group conversation."""
    at = _ensure_activity_type(
        code="group.livewire.message",
        label="Group Chat Message",
        default_channel="activity",
        default_priority="low",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(message.sender),
        actor_id=_id(message.sender),
        actor_label="user",
        object_content_type=_ct(message),
        object_id=_id(message),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="messaged",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={},
        dedupe_key=f"{at.code}:{_id(message)}",
        aggregate_key=f"livewire:{_id(group)}:{timezone.now():%Y%m%d}",
        audience={
            "type": "group_members",
            "group_id": str(_id(group)),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )
