# classifications/stackroom_signals.py — Stackroom ingest triggers for Idea Tags.
#
# Only Tag.is_idea=True is indexed (ADR-0058 D7, SH-3). Ordinary Tags are not
# Ideas and never reach Stackroom from here.

from django.db.models.signals import post_save
from django.dispatch import receiver

from classifications.models import Tag


@receiver(post_save, sender=Tag)
def tag_post_save(sender, instance, **kwargs):
    if not instance.is_idea:
        return
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    enqueue_stackroom_ingest(instance, reason="tag_idea_save")
