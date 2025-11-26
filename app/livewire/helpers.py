# apps/livewire/helpers.py

from chat.models import Conversation, ConversationContext
from contexts.models import Context
from livewire.services import sync_participants_for_context_link


def get_or_create_default_conversation(definition_slug, anchor_obj, title=None, lock_participants=True):
    """
    Ensure there is a default conversation for (definition_slug, anchor_obj),
    and if locked, sync participants from the anchor’s registry.
    """
    ctx = Context.for_anchor(definition_slug, anchor_obj, label=str(anchor_obj))

    cc = (
        ConversationContext.objects
        .filter(context=ctx, is_default_for_context=True)
        .select_related("conversation")
        .first()
    )
    if cc:
        convo = cc.conversation
        if lock_participants and not convo.lock_participants:
            convo.lock_participants = True
            convo.save(update_fields=["lock_participants"])
        if convo.lock_participants:
            sync_participants_for_context_link(cc)
        return convo

    convo = Conversation.objects.create(
        title=title or f"{ctx.label} Chat",
        lock_participants=lock_participants,
    )
    cc = ConversationContext.objects.create(
        conversation=convo,
        context=ctx,
        is_default_for_context=True,
    )
    if lock_participants:
        sync_participants_for_context_link(cc)
    return convo
