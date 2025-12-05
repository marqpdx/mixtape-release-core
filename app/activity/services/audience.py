# activity/services/audience.py
"""
Audience Resolution Service

Resolves audience specifications from Actions into concrete lists of User objects.
Supports various audience types: direct users, group members, post participants, etc.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model


User = get_user_model()


def resolve_audience(audience_spec: dict, action) -> list[User]:
    """
    Resolve audience specification to list of User objects.

    Audience spec formats:

    1) Direct users:
        {
            "type": "users",
            "ids": ["uuid1", "uuid2"],
            "exclude_actor": true
        }

    2) Group members:
        {
            "type": "group_members",
            "group_id": "uuid",
            "exclude_actor": true
        }

    3) Multiple groups:
        {
            "type": "group_members_multi",
            "group_ids": ["uuid1", "uuid2"],
            "exclude_actor": true
        }

    4) Post participants (commenters, reactors):
        {
            "type": "post_participants",
            "post_id": "uuid",
            "exclude_actor": true
        }

    Args:
        audience_spec: Dictionary specifying the audience
        action: The Action object (for actor exclusion)

    Returns:
        List of User objects to notify
    """
    audience_type = audience_spec.get("type")
    exclude_actor = audience_spec.get("exclude_actor", False)

    users = []

    if audience_type == "users":
        # Direct user IDs
        user_ids = audience_spec.get("ids", [])
        users = list(User.objects.filter(pk__in=user_ids, is_active=True))

    elif audience_type == "group_members":
        # Single group's members
        group_id = audience_spec.get("group_id")
        if group_id:
            users = _resolve_group_members(group_id)

    elif audience_type == "group_members_multi":
        # Multiple groups' members (deduplicated)
        group_ids = audience_spec.get("group_ids", [])
        users = _resolve_multi_group_members(group_ids)

    elif audience_type == "post_participants":
        # Users who have interacted with a post
        post_id = audience_spec.get("post_id")
        if post_id:
            users = _resolve_post_participants(post_id)

    else:
        # Unknown audience type - log warning and return empty
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Unknown audience type: {audience_type}")
        return []

    # Exclude actor if requested
    if exclude_actor and action.actor_id:
        users = [u for u in users if str(u.pk) != str(action.actor_id)]

    # Deduplicate
    seen_ids = set()
    unique_users = []
    for u in users:
        if u.pk not in seen_ids:
            seen_ids.add(u.pk)
            unique_users.append(u)

    return unique_users


def _resolve_group_members(group_id: str) -> list[User]:
    """Get all active members of a group."""
    try:
        from groups.models import GroupMembership
        return list(User.objects.filter(
            group_memberships__group_id=group_id,
            group_memberships__is_active=True,
            is_active=True
        ).distinct())
    except ImportError:
        # groups app not available yet
        return []


def _resolve_multi_group_members(group_ids: list[str]) -> list[User]:
    """Get all active members from multiple groups (deduplicated)."""
    try:
        from groups.models import GroupMembership
        return list(User.objects.filter(
            group_memberships__group_id__in=group_ids,
            group_memberships__is_active=True,
            is_active=True
        ).distinct())
    except ImportError:
        return []


def _resolve_post_participants(post_id: str) -> list[User]:
    """
    Get users who have interacted with a post (author, commenters, reactors).

    TODO: Implement based on your comment/reaction models.
    For now, returns empty list.
    """
    return []
