# chat/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F
from .models import ChatMessage, ConversationParticipant, ConversationStatusTracker

@receiver(post_save, sender=ConversationParticipant)
def create_status_tracker(sender, instance, created, **kwargs):
    if created:
        ConversationStatusTracker.objects.get_or_create(
            user=instance.user,
            conversation=instance.conversation,
        )

@receiver(post_save, sender=ChatMessage)
def bump_unreads(sender, instance: ChatMessage, created, **kwargs):
    if not created:
        return
    ConversationStatusTracker.objects \
        .filter(conversation=instance.conversation) \
        .exclude(user=instance.sender) \
        .update(unread_count=F("unread_count") + 1)

