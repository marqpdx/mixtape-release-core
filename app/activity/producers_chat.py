# activity/producers_chat.py
from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from activity.models import Action, ActionOutbox, ActivityType
from activity.services.validation import validate_audience_spec


# ---------- Small helpers ----------
def _id(obj) -> str:
    return str(getattr(obj, "pk", obj))

def _ct(obj) -> ContentType:
    return ContentType.objects.get_for_model(obj.__class__)

def _ensure_activity_type(
    code: str,
    *,
    title: str,
    default_channel: str = "activity",
    default_priority: str = "normal",
    suppressible_by_user: bool = True,
) -> ActivityType:
    """
    Ensure an ActivityType row exists. ActivityType inherits from BaseData,
    so we set title/summary instead of 'label'.
    """
    at, _ = ActivityType.objects.get_or_create(
        code=code,
        defaults=dict(
            title=title,
            summary="",
            default_channel=default_channel,
            default_priority=default_priority,
            suppressible_by_user=suppressible_by_user,
        ),
    )
    return at

def _create_action_and_outbox(**kwargs) -> Action:
    """
    Create Action + Outbox. Fanout is triggered by ActionOutbox post_save.
    """
    validate_audience_spec(kwargs.get("audience", {}))
    action = Action.objects.create(**kwargs)
    ActionOutbox.objects.create(action=action)
    return action


# =====================================================================
# 1) on_chat_mention: Mention(s) in a conversation message (CRITICAL)
# =====================================================================
def on_chat_mention(*, message, conversation, mentioned_users):
    """
    Called when the message body mentions specific users.
    - Channel: messages
    - Priority: critical
    - Audience: mentioned users (excluding the actor)
    - Dedupe: per-message
    - Aggregate: per conversation per minute (for bursty mentions)
    """
    at = _ensure_activity_type(
        code="chat.mention",
        title="Chat Mention",
        default_channel="messages",
        default_priority="critical",
        suppressible_by_user=False,  # generally we don't allow suppressing mentions
    )

    _create_action_and_outbox(
        # actor
        actor_content_type=_ct(message.sender),
        actor_id=_id(message.sender),
        actor_label="user",

        # object & context
        object_content_type=_ct(message),
        object_id=_id(message),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),

        # semantics
        activity_type=at,
        verb="mentioned",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        # optional metadata for UI
        metadata={"message_preview": getattr(message, "text", "")[:140]},

        # dedupe / aggregate
        dedupe_key=f"{at.code}:message:{_id(message)}",
        aggregate_key=f"chat-mentions:{_id(conversation)}:{timezone.now():%Y%m%d%H%M}",

        # audience
        audience={"type": "users", "ids": [str(u.pk) for u in mentioned_users], "exclude_actor": True},

        occurs_at=timezone.now(),
    )


# ==================================================================================
# 1b) on_new_chat_message: new message in any conversation (normal priority)
#     Fan out to all participants except the sender.
# ==================================================================================
def on_new_chat_message(*, message, conversation, recipients):
    """
    Called on every new ChatMessage for all participants except the sender.

    - Channel: messages (dedicated inbox tab / navbar badge)
    - Priority: normal
    - Suppressible: yes (users can mute conversations)
    - Dedupe: per message (so each message gets one Notification row per recipient)
    - Aggregate: per-conversation per-minute (rolling rollup for burst messages)

    `recipients` must exclude the sender — caller is responsible for the filter.
    """
    if not recipients:
        return

    at = _ensure_activity_type(
        code="chat.message.new",
        title="New Message",
        default_channel="messages",
        default_priority="normal",
        suppressible_by_user=True,
    )

    recipient_ids = [str(u.pk) for u in recipients]

    _create_action_and_outbox(
        actor_content_type=_ct(message.sender),
        actor_id=_id(message.sender),
        actor_label="user",

        object_content_type=_ct(message),
        object_id=_id(message),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),

        activity_type=at,
        verb="sent",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        metadata={
            "message_preview": (getattr(message, "text", "") or "")[:140],
            "conversation_slug": str(conversation.slug),
            "conversation_title": str(getattr(conversation, "title", "") or ""),
        },

        # Dedupe per message so each message gets its own row
        dedupe_key=f"chat.message.new:{_id(message)}",
        # Rolling rollup — groups burst messages in the same conversation
        aggregate_key=f"chat-messages:{_id(conversation)}:{timezone.now():%Y%m%d%H%M}",

        audience={"type": "users", "ids": recipient_ids, "exclude_actor": False},

        occurs_at=timezone.now(),
    )


# ==================================================================================
# 2) on_conversation_participant_added: user is added to a conversation (SYSTEM-ish)
# ==================================================================================
def on_conversation_participant_added(*, conversation, added_user, added_by):
    """
    Inform a user they were added to a conversation.
    - Channel: activity (drawer)
    - Priority: normal
    - Audience: the added user
    - Dedupe: per (conversation, added_user)
    - Aggregate: per conversation per day (e.g., repeated add/remove churn)
    """
    at = _ensure_activity_type(
        code="chat.participant.added",
        title="Added to Conversation",
        default_channel="activity",
        default_priority="normal",
        suppressible_by_user=True,
    )

    _create_action_and_outbox(
        actor_content_type=_ct(added_by),
        actor_id=_id(added_by),
        actor_label="user",

        object_content_type=_ct(conversation),
        object_id=_id(conversation),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),

        activity_type=at,
        verb="added",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        metadata={"conversation_name": getattr(conversation, "name", "")},

        dedupe_key=f"{at.code}:conversation:{_id(conversation)}:user:{_id(added_user)}",
        aggregate_key=f"chat-participants:{_id(conversation)}:{timezone.now():%Y%m%d}",

        audience={"type": "users", "ids": [str(_id(added_user))], "exclude_actor": False},

        occurs_at=timezone.now(),
    )


# ==================================================================================
# 3) on_conversation_created: notify initial participants (except the creator)
# ==================================================================================
def on_conversation_created(*, conversation, creator, initial_participants):
    """
    Notify invitees that a new conversation with them has been created.
    - Channel: activity
    - Priority: normal
    - Audience: participants except the creator
    - Dedupe: per (conversation, recipient)
    - Aggregate: per conversation per day
    """
    at = _ensure_activity_type(
        code="chat.conversation.created",
        title="Conversation Created",
        default_channel="activity",
        default_priority="normal",
        suppressible_by_user=True,
    )

    recipient_ids = [str(u.pk) for u in initial_participants if u.pk != creator.pk]

    if not recipient_ids:
        return  # nothing to notify

    _create_action_and_outbox(
        actor_content_type=_ct(creator),
        actor_id=_id(creator),
        actor_label="user",

        object_content_type=_ct(conversation),
        object_id=_id(conversation),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),

        activity_type=at,
        verb="created",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        metadata={"conversation_name": getattr(conversation, "name", "")},

        dedupe_key=f"{at.code}:conversation:{_id(conversation)}",
        aggregate_key=f"chat-conversation:{_id(conversation)}:{timezone.now():%Y%m%d}",

        audience={"type": "users", "ids": recipient_ids, "exclude_actor": False},

        occurs_at=timezone.now(),
    )


# ==================================================================================
# 4) on_conversation_updated: name/topic/locked updated (digestable QoL)
# ==================================================================================
def on_conversation_updated(*, conversation, updated_by, changes: dict):
    """
    Small system event: rename, topic, locked/unlocked, etc.
    - Channel: activity
    - Priority: normal (or low if you prefer)
    - Audience: all current participants except updater (optional)
    - Dedupe: per (conversation, change-set signature)
    - Aggregate: per conversation per day
    """
    at = _ensure_activity_type(
        code="chat.conversation.updated",
        title="Conversation Updated",
        default_channel="activity",
        default_priority="normal",
        suppressible_by_user=True,
    )

    # Get participant user ids (replace with your participation query)
    # e.g., ConversationParticipant.objects.filter(conversation=conversation).values_list("user_id", flat=True)
    if hasattr(conversation, "participants"):  # if you have related_name="participants"
        participant_ids = list(conversation.participants.values_list("user_id", flat=True))
    else:
        participant_ids = []

    # Exclude the actor if present
    recipient_ids = [str(uid) for uid in participant_ids if str(uid) != _id(updated_by)]

    if not recipient_ids:
        return

    # a small signature of the changes for dedupe purposes
    # (e.g., {"name":"New Name","locked":true}) -> "name,locked"
    change_keys = ",".join(sorted(changes.keys())) if changes else "meta"

    _create_action_and_outbox(
        actor_content_type=_ct(updated_by),
        actor_id=_id(updated_by),
        actor_label="user",

        object_content_type=_ct(conversation),
        object_id=_id(conversation),
        context_content_type=_ct(conversation),
        context_id=_id(conversation),

        activity_type=at,
        verb="updated",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        metadata={"changes": changes},

        dedupe_key=f"{at.code}:conversation:{_id(conversation)}:{change_keys}",
        aggregate_key=f"chat-conversation-updates:{_id(conversation)}:{timezone.now():%Y%m%d}",

        audience={"type": "users", "ids": recipient_ids, "exclude_actor": False},

        occurs_at=timezone.now(),
    )
