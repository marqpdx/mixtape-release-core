# atrium/signals.py
#
# Signals for the Atrium surface.
# Continuous Keeper turn-count trigger: after each assistant entry is saved,
# check whether the cadence threshold has been reached and fire keeper_compact_task.

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender="atrium.AtriumSessionEntry")
def on_session_entry_saved(sender, instance, created, **kwargs):
    """
    After each AtriumSessionEntry is saved, check if the Continuous Keeper
    turn threshold has been reached. Only fires on assistant entries (user
    entries don't advance the turn count).
    """
    if not created:
        return

    from atrium.models import AtriumSessionRole
    if instance.role != AtriumSessionRole.ASSISTANT:
        return

    try:
        from atrium.ai.service import _trigger_keeper_if_due
        _trigger_keeper_if_due(instance.session)
    except Exception as exc:
        logger.warning("[atrium] on_session_entry_saved keeper check failed: %s", exc)
