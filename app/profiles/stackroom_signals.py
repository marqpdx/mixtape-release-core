# profiles/stackroom_signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver

from profiles.models import UserProfile


@receiver(post_save, sender=UserProfile)
def user_profile_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    enqueue_stackroom_ingest(instance, reason="user_profile_save")
