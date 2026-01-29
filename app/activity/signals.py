# activity/signals.py (continued)

from django.db.models.signals import post_save
from django.dispatch import receiver

from activity.models import ActionOutbox
from activity.tasks import fanout_action_task


@receiver(post_save, sender=ActionOutbox)
def _outbox_created(sender, instance: ActionOutbox, created: bool, **kwargs):
    if created:
        fanout_action_task.delay(str(instance.action_id))
