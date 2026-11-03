# switchboard/tasks.py
#
# SW-11.12 (graceful degradation): enqueue_switchboard_task (dispatch.py)
# catches a broker-unreachable failure at send_task time. It cannot catch
# the other failure mode -- the broker is fine but Switchboard's own worker
# is down or stalled, so a dispatched ActionRun never advances past PENDING
# (or past RUNNING, if Switchboard crashes mid-task) and the frontend's
# useActionRun poll never reaches a terminal state. This sweep catches that
# case on a beat schedule, on the "polling" queue -- deliberately not
# "switchboard", since its whole job is to notice when that queue's worker
# has stopped responding.

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from initiatives.models import ActionRun, ActionRunStatus

logger = logging.getLogger(__name__)

STALE_ACTION_RUN_MINUTES = getattr(settings, "SWITCHBOARD_STALE_ACTION_RUN_MINUTES", 15)


@shared_task(name="switchboard.tasks.sweep_stale_action_runs")
def sweep_stale_action_runs():
    """Mark switchboard-routed ActionRuns stuck in PENDING/RUNNING past the
    staleness window as FAILED, so polling clients reach a terminal state
    instead of spinning forever against a down or stalled Switchboard worker."""
    cutoff = timezone.now() - timezone.timedelta(minutes=STALE_ACTION_RUN_MINUTES)
    stale = ActionRun.objects.filter(
        service_name="switchboard",
        status__in=[ActionRunStatus.PENDING, ActionRunStatus.RUNNING],
        started_at__lt=cutoff,
    )
    now = timezone.now()
    count = stale.update(
        status=ActionRunStatus.FAILED,
        error_payload={"error": "switchboard_unavailable", "detail": "No response from Switchboard within the timeout window."},
        completed_at=now,
        updated_at=now,  # .update() bypasses auto_now
    )
    if count:
        logger.warning("Swept %d stale switchboard ActionRun(s) past %d minutes", count, STALE_ACTION_RUN_MINUTES)
    return {"swept": count}
