# writing/stackroom_signals.py — Stackroom ingest triggers for writing models.

from django.db.models.signals import post_save
from django.dispatch import receiver

from writing.models import Seed, WorkingDocument, WritingPiece
from commons.models import Leaf


@receiver(post_save, sender=Seed)
def seed_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    enqueue_stackroom_ingest(instance, reason="seed_save")


@receiver(post_save, sender=Leaf)
def leaf_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    enqueue_stackroom_ingest(instance, reason="leaf_save")


@receiver(post_save, sender=WorkingDocument)
def working_document_post_save(sender, instance, **kwargs):
    from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
    enqueue_stackroom_ingest(instance, reason="working_document_save")


@receiver(post_save, sender=WritingPiece)
def writing_piece_post_save(sender, instance, **kwargs):
    if instance.status == "published":
        from inkwell.stackroom_enqueue import enqueue_stackroom_ingest
        enqueue_stackroom_ingest(instance, reason="writing_piece_published")
