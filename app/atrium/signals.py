# atrium/signals.py
#
# Signals for the Atrium surface.
# Continuous Keeper turn-count trigger: when an agent's reply finishes, check whether
# the cadence threshold has been reached and fire keeper_compact_task.

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="atrium.DialogueEntry")
def on_dialogue_entry_saved(sender, instance, created, **kwargs):
    """
    When a reply is finished, check if the Continuous Keeper turn threshold has been
    reached. Replies are created pending and finished later by the runtime worker, so
    this fires on the save that marks them done, not on creation. The person's own
    entries don't advance the turn count.
    """
    from atrium.models import DialogueEntryStatus, DialogueRole

    if instance.role != DialogueRole.ASSISTANT or instance.status != DialogueEntryStatus.DONE:
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "status" not in update_fields:
        return

    try:
        from atrium.ai.service import _trigger_keeper_if_due
        _trigger_keeper_if_due(instance.dialogue)
    except Exception as exc:
        logger.warning("[atrium] on_dialogue_entry_saved keeper check failed: %s", exc)
