# apps/livewire/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from chat.models import ConversationContext
from livewire.services import sync_participants_for_context_link


@receiver(post_save, sender=ConversationContext)
def sync_on_context_save(sender, instance: ConversationContext, created, **kwargs):
    # Only sync when either first bound or the default flag flips
    if instance.is_default_for_context and instance.conversation.lock_participants:
        sync_participants_for_context_link(instance)
