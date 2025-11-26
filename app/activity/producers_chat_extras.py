# activity/producers_chat_extras.py

from __future__ import annotations
from typing import Iterable, List
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

from activity.models import Action, ActionOutbox, ActivityType
from activity.tasks import fanout_action_task
from activity.services.mentions import expand_mention_to_users

User = get_user_model()

def _ct(obj): return ContentType.objects.get_for_model(obj.__class__)
def _id(obj): return str(getattr(obj, "pk", obj))

def _ensure_activity_type(code, title, default_channel, default_priority, suppressible):
    at, _ = ActivityType.objects.get_or_create(
        code=code,
        defaults=dict(
            title=title, summary="",
            default_channel=default_channel,
            default_priority=default_priority,
            suppressible_by_user=suppressible,
        ),
    )
    return at

def _create_and_dispatch(action_kwargs):
    action = Action.objects.create(**action_kwargs)
    ActionOutbox.objects.create(action=action)
    # fire immediately in dev; in prod you might rely on post_save on outbox or Celery async
    fanout_action_task.delay(str(action.pk))
    return action

# ---------------------------------------------------------------------
# MENTIONS: produce ONE Action per message (with audience = all mentioned users)
# ---------------------------------------------------------------------
def produce_mentions_for_message(*, message, conversation, actor_user, mentions_queryset) -> bool:
    """
    Build a SINGLE Action for a message that @mentioned users and fan out to all recipients.
    - Expands group mentions to members
    - Excludes actor from audience
    - Idempotent per message via dedupe_key
    Returns True if an Action was created.
    """
    at = _ensure_activity_type("chat.mention", "Chat Mention", "messages", "critical", False)

    # Deduplicate recipients across multiple MessageMention rows
    user_ids: List[str] = []
    seen = set()

    for mention in mentions_queryset:
        users = expand_mention_to_users(mention)
        for u in users:
            if u.pk == actor_user.pk:
                continue
            if u.pk not in seen:
                seen.add(u.pk)
                user_ids.append(str(u.pk))

    if not user_ids:
        return False

    dedupe_key = f"chat-mention:{_id(conversation)}:{_id(message)}"
    # Avoid duplicate Actions if this gets called multiple times
    if Action.objects.filter(dedupe_key=dedupe_key).exists():
        return False

    _create_and_dispatch(dict(
        actor_content_type=_ct(actor_user),
        actor_id=_id(actor_user),
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

        dedupe_key=dedupe_key,
        aggregate_key=f"chat-mentions:{_id(conversation)}:{timezone.now():%Y%m%d%H%M}",

        audience={"type": "users", "ids": user_ids, "exclude_actor": True},
        occurs_at=timezone.now(),
    ))
    return True

# ---------------------------------------------------------------------
# REACTIONS: notify the ORIGINAL MESSAGE SENDER (digest/low)
# ---------------------------------------------------------------------
def produce_reaction_notification(*, reaction) -> bool:
    """
    Create/merge a low-priority notification to the original message sender
    when someone reacts to their message.
    - Skips self-reactions
    - dedupe_key by message (→ one row per message per recipient)
    - aggregate_key rolls up over time
    """
    msg = reaction.message
    sender = msg.sender
    reactor = reaction.user
    if sender_id := getattr(sender, "pk", None):
        if reactor and reactor.pk == sender_id:
            return False  # no self-notify

    at = _ensure_activity_type("chat.message.reaction", "Reaction to Your Message", "activity", "low", True)

    _create_and_dispatch(dict(
        actor_content_type=_ct(reactor),
        actor_id=_id(reactor),
        actor_label="user",

        object_content_type=_ct(reaction),
        object_id=_id(reaction),
        context_content_type=_ct(msg.conversation),
        context_id=_id(msg.conversation),

        activity_type=at,
        verb="reacted",
        activity_code=at.code,
        channel=at.default_channel,
        priority=at.default_priority,

        metadata={
            "reaction_name": reaction.reaction_name,
            "message_preview": getattr(msg, "text", "")[:140],
        },

        dedupe_key=f"chat-reaction:{_id(msg)}:{_id(sender)}",
        aggregate_key=f"chat-reactions:{_id(msg)}:{timezone.now():%Y%m%d%H}",

        audience={"type": "users", "ids": [str(sender.pk)], "exclude_actor": True},
        occurs_at=timezone.now(),
    ))
    return True
