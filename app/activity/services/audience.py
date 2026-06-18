# activity/services/audience.py
"""
Audience Resolution Service

Resolves audience specifications from Actions into concrete lists of User objects.
Supports various audience types: direct users, group members, post participants, etc.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType


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
            users = _resolve_post_participants(post_id, action)

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
        from django.contrib.contenttypes.models import ContentType
        from groups.models import GroupMembership
        user_ct = ContentType.objects.get_for_model(User)
        member_ids = GroupMembership.objects.filter(
            group_id=group_id,
            member_content_type=user_ct,
            is_active=True,
        ).values_list("member_object_id", flat=True)
        return list(User.objects.filter(pk__in=member_ids, is_active=True))
    except ImportError:
        return []


def _resolve_multi_group_members(group_ids: list[str]) -> list[User]:
    """Get all active members from multiple groups (deduplicated)."""
    try:
        from django.contrib.contenttypes.models import ContentType
        from groups.models import GroupMembership
        user_ct = ContentType.objects.get_for_model(User)
        member_ids = GroupMembership.objects.filter(
            group_id__in=group_ids,
            member_content_type=user_ct,
            is_active=True,
        ).values_list("member_object_id", flat=True).distinct()
        return list(User.objects.filter(pk__in=member_ids, is_active=True))
    except ImportError:
        return []


def _resolve_post_participants(post_id: str, action=None) -> list[User]:
    """
    Get users who have interacted with a post (author, commenters, reactors).
    Attempts to resolve the post from action context or known models.
    """
    post_obj = None

    if action and action.context_id and str(action.context_id) == str(post_id):
        post_obj = action.context
    elif action and action.context_content_type_id:
        try:
            post_obj = action.context_content_type.get_object_for_this_type(pk=post_id)
        except Exception:
            post_obj = None

    if not post_obj:
        for model_path in (
            "writing.WritingPiece",
            "dispatch.Post",
            "threadworks.Post",
        ):
            try:
                app_label, model_name = model_path.split(".")
                model = ContentType.objects.get(app_label=app_label, model=model_name.lower()).model_class()
                post_obj = model.objects.filter(pk=post_id).first()
                if post_obj:
                    break
            except Exception:
                continue

    if not post_obj:
        return []

    participant_ids = set()

    author_id = getattr(post_obj, "author_id", None)
    if author_id:
        participant_ids.add(author_id)

    model_label = post_obj._meta.label_lower

    if model_label == "writing.writingpiece":
        try:
            from writing.models import WritingComment, CommentLike
            commenter_ids = WritingComment.objects.filter(
                piece_id=post_obj.pk
            ).values_list("author_id", flat=True)
            participant_ids.update(commenter_ids)

            liker_ids = CommentLike.objects.filter(
                comment__piece_id=post_obj.pk
            ).values_list("user_id", flat=True)
            participant_ids.update(liker_ids)
        except Exception:
            pass

    elif model_label == "threadworks.post":
        try:
            from threadworks.models import Post, PostReaction
            reply_ids = Post.objects.filter(
                parent_id=post_obj.pk
            ).values_list("author_id", flat=True)
            participant_ids.update(reply_ids)

            reactor_ids = PostReaction.objects.filter(
                post_id=post_obj.pk
            ).values_list("user_id", flat=True)
            participant_ids.update(reactor_ids)
        except Exception:
            pass

    return list(User.objects.filter(pk__in=participant_ids, is_active=True))
