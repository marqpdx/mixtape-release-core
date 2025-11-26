# activity/producers.py
from __future__ import annotations
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from activity.models import Action, ActionOutbox, ActivityType

def _id(obj) -> str:
    return str(getattr(obj, "pk", obj))

def _ct(obj) -> ContentType:
    return ContentType.objects.get_for_model(obj.__class__)

def _ensure_activity_type(code: str, *, label: str, default_channel: str = "activity",
                          default_priority: str = "normal", suppressible: bool = True) -> ActivityType:
    at, _ = ActivityType.objects.get_or_create(
        code=code,
        defaults=dict(
            title=label,   # BaseData: title replaces label
            summary="",
            default_channel=default_channel,
            default_priority=default_priority,
            suppressible_by_user=suppressible,
        ),
    )
    return at

def _create_action_and_outbox(**kwargs) -> Action:
    action = Action.objects.create(**kwargs)
    ActionOutbox.objects.create(action=action)
    return action

# 1) Group post created (cross-post-friendly via dedupe_key = post:<id>)
def on_group_post_created(*, post, groups, actor_user=None):
    at = _ensure_activity_type(
        code="group.post.created",
        label="New Post in Group",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    actor_label = "user" if actor_user else "group"
    actor_ct = _ct(actor_user) if actor_user else _ct(groups[0])  # or None if "system"

    _create_action_and_outbox(
        actor_content_type=actor_ct,
        actor_id=_id(actor_user) if actor_user else _id(groups[0]),
        actor_label=actor_label,
        object_content_type=_ct(post),
        object_id=_id(post),
        context_content_type=_ct(groups[0]),
        context_id=_id(groups[0]),
        activity_type=at,
        verb="posted",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={},
        dedupe_key=f"post:{_ct(post).pk}:{_id(post)}",
        aggregate_key=f"post:{_ct(post).pk}:{_id(post)}",
        audience={"type": "group_members_multi", "group_ids": [str(g.pk) for g in groups], "exclude_actor": True},
        occurs_at=timezone.now(),
    )

# 2) Comment created (roll up under comments:post:<id>)
def on_comment_created(*, comment, post):
    at = _ensure_activity_type(
        code="post.comment.created",
        label="New Comment on Post",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(comment.author),
        actor_id=_id(comment.author),
        actor_label="user",
        object_content_type=_ct(comment),
        object_id=_id(comment),
        context_content_type=_ct(post),
        context_id=_id(post),
        activity_type=at,
        verb="commented",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={},
        dedupe_key=f"post:{_ct(post).pk}:{_id(post)}",              # canonical to the post
        aggregate_key=f"comments:post:{_ct(post).pk}:{_id(post)}",  # rollup key
        audience={"type": "post_participants", "post_id": _id(post), "exclude_actor": True},
        occurs_at=timezone.now(),
    )

# 3) Chat @mention (Messages channel; CRITICAL)
def on_chat_mention(*, message, conversation, mentioned_users):
    at = _ensure_activity_type(
        code="chat.mention",
        label="Chat Mention",
        default_channel="messages",
        default_priority="critical",
        suppressible=False,
    )
    _create_action_and_outbox(
        actor_content_type=_ct(message.sender),
        actor_id=_id(message.sender),
        actor_label="user",
        object_content_type=_ct(message),
        object_id=_id(message),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),
        activity_type=at,
        verb="mentioned",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={"message_preview": getattr(message, "text", "")[:140]},
        dedupe_key=f"chat-mention:{_id(conversation)}:{_id(message)}",
        aggregate_key=f"chat-mentions:{_id(conversation)}:{timezone.now():%Y%m%d%H%M}",
        audience={"type": "users", "ids": [str(u.pk) for u in mentioned_users], "exclude_actor": True},
        occurs_at=timezone.now(),
    )

# 4) Group announcement (actor can be the Group; Activity channel)
def on_group_announcement(*, group, announcement, authored_by=None):
    at = _ensure_activity_type(
        code="group.announcement",
        label="Group Announcement",
        default_channel="activity",
        default_priority="normal",
        suppressible=True,
    )
    # Actor is the group (or the steward if you prefer)
    _create_action_and_outbox(
        actor_content_type=_ct(group),
        actor_id=_id(group),
        actor_label="group",
        object_content_type=_ct(announcement),
        object_id=_id(announcement),
        context_content_type=_ct(group),
        context_id=_id(group),
        activity_type=at,
        verb="announced",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,
        metadata={"title": getattr(announcement, "title", "")},
        dedupe_key=f"announcement:{_ct(announcement).pk}:{_id(announcement)}",
        aggregate_key=f"announcement:{_ct(group).pk}:{_id(group)}:{timezone.now():%Y%m%d}",
        audience={"type": "group_members", "group_id": _id(group), "exclude_actor": True},
        occurs_at=timezone.now(),
    )
