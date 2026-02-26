# writing/producers.py
"""
Activity producers for Leaf/Storyline events.

- Leaf published → notify followers
- Follow created → notify target user
- Leaf comment → notify leaf author
"""
from __future__ import annotations

from activity.producers import (
    _create_action_and_outbox,
    _ct,
    _ensure_activity_type,
    _id,
)


def on_leaf_published(*, leaf, author):
    """Notify followers when a new Leaf is published to Storyline."""
    from fundamentals.services.follow_service import get_following_ids

    # Get users who follow this author — they should see the notification
    from fundamentals.models import Follow
    follower_ids = list(
        Follow.objects.filter(
            following=author,
            deleted_at__isnull=True,
        ).values_list("follower_id", flat=True)
    )

    if not follower_ids:
        return

    at = _ensure_activity_type(
        code="storyline.leaf.published",
        label="New Storyline Post",
        default_channel="in_app",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(author),
        actor_id=_id(author),
        actor_label="user",
        object_content_type=_ct(leaf),
        object_id=_id(leaf),
        activity_type=at,
        audience_type="users",
        audience_ids=[str(uid) for uid in follower_ids],
        context={"leaf_kind": leaf.kind, "is_reference": leaf.is_reference},
    )


def on_follow_created(*, follower, target):
    """Notify a user when someone follows them."""
    at = _ensure_activity_type(
        code="social.follow.created",
        label="New Follower",
        default_channel="in_app",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(follower),
        actor_id=_id(follower),
        actor_label="user",
        object_content_type=_ct(follower),
        object_id=_id(follower),
        activity_type=at,
        audience_type="users",
        audience_ids=[str(target.id)],
        context={},
    )


def on_leaf_comment_created(*, comment, leaf):
    """Notify leaf author when someone comments on their Leaf."""
    # Don't notify if commenting on own leaf
    if comment.author_id == leaf.author_id:
        return

    at = _ensure_activity_type(
        code="storyline.leaf.comment",
        label="New Comment on Storyline Post",
        default_channel="in_app",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(comment.author),
        actor_id=_id(comment.author),
        actor_label="user",
        object_content_type=_ct(comment),
        object_id=_id(comment),
        activity_type=at,
        audience_type="users",
        audience_ids=[str(leaf.author_id)],
        context={"leaf_id": str(leaf.id)},
    )
