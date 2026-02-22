# threadworks/producers.py
"""Activity producers for threadworks (forum) events."""
from __future__ import annotations

from django.utils import timezone

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_threadworks_post_created(*, post, discussion, forum, group):
    """Notify group members when a new discussion post is created."""
    at = _ensure_activity_type(
        code="group.threadworks.post_created",
        label="New Discussion Post",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(post.author),
        actor_id=_id(post.author),
        actor_label="user",
        object_content_type=_ct(post),
        object_id=_id(post),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="posted",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={
            "discussion_title": discussion.title,
            "forum_title": forum.title,
        },
        dedupe_key=f"{at.code}:{_id(post)}",
        aggregate_key=f"threadworks:{_id(group)}",
        audience={
            "type": "group_members",
            "group_id": str(_id(group)),
            "exclude_actor": True,
        },
        occurs_at=timezone.now(),
    )
