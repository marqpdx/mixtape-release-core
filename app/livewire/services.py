# apps/livewire/services.py
from django.contrib.auth import get_user_model
from django.db import transaction

from chat.models import Conversation, ConversationContext, ConversationParticipant
from livewire.participant_sources import users_for_anchor


User = get_user_model()


@transaction.atomic
def sync_participants_for_context_link(cc: ConversationContext, keep_admin_creator=True) -> dict:
    """
    Sync conversation participants from the cc.context.anchor when
    cc.is_default_for_context AND cc.conversation.lock_participants is True.

    Returns a summary dict: {"added": N, "removed": N, "kept": N}
    """
    convo = cc.conversation
    if not (cc.is_default_for_context and convo.lock_participants):
        return {"added": 0, "removed": 0, "kept": 0}

    anchor = cc.context.anchor
    desired_ids: set[int] = users_for_anchor(anchor)

    # Optionally ensure the creator stays admin (if present)
    admin_keep: set[int] = set()
    if keep_admin_creator and convo.created_by_id:
        admin_keep.add(convo.created_by_id)

    current_qs = ConversationParticipant.objects.filter(conversation=convo)
    current_ids = set(current_qs.values_list("user_id", flat=True))

    to_add = desired_ids - current_ids
    to_remove = current_ids - desired_ids - admin_keep
    to_keep = current_ids & desired_ids

    # add
    if to_add:
        bulk = [
            ConversationParticipant(conversation=convo, user_id=uid)
            for uid in to_add
        ]
        ConversationParticipant.objects.bulk_create(bulk, ignore_conflicts=True)

    # remove
    if to_remove:
        ConversationParticipant.objects.filter(
            conversation=convo, user_id__in=to_remove
        ).delete()

    # ensure creator stays in conversation if they were admin
    if convo.created_by_id and convo.created_by_id in admin_keep:
        ConversationParticipant.objects.get_or_create(
            conversation=convo,
            user_id=convo.created_by_id,
        )

    return {"added": len(to_add), "removed": len(to_remove), "kept": len(to_keep)}


def sync_participants_for_conversation(convo: Conversation) -> dict:
    """
    If the conversation has a default context and is locked, sync from that anchor.
    If multiple contexts ever exist, prefers the default one.
    """
    cc = convo.default_context_link()
    if not cc:
        return {"added": 0, "removed": 0, "kept": 0}
    return sync_participants_for_context_link(cc)
