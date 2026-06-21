# threadworks/stackroom_signals.py
#
# Post saves on Discussion and Post both enqueue Discussion re-ingest.
# Per stackroom-threadworks-ingest-design.md §6.

from django.db.models.signals import post_save
from django.dispatch import receiver

from threadworks.models import Discussion, FeedPost, Post


@receiver(post_save, sender=Discussion)
def discussion_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_deactivate, enqueue_stackroom_ingest
    if instance.is_deleted:
        enqueue_stackroom_deactivate(instance, reason="discussion_deleted")
    else:
        enqueue_stackroom_ingest(instance, reason="discussion_save")


@receiver(post_save, sender=FeedPost)
def feed_post_stackroom_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_deactivate, enqueue_stackroom_ingest
    if instance.is_deleted:
        enqueue_stackroom_deactivate(instance, reason="feed_post_deleted")
    else:
        enqueue_stackroom_ingest(instance, reason="feed_post_save")


@receiver(post_save, sender=Post)
def post_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    container = instance.discussion or instance.feed_post
    if container:
        enqueue_stackroom_ingest(container, reason="post_save")
