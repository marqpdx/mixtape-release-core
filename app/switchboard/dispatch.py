# switchboard/dispatch.py
#
# SW-11.12 (graceful degradation): a single seam for every enqueue of a
# switchboard-queue Celery task. If the broker itself is unreachable,
# send_task raises before anything is ever queued -- previously unguarded
# at every call site but one (heddle.lifecycle._enqueue). This wraps that
# failure into a clear FAILED ActionRun instead of an unhandled 500 and a
# PENDING ActionRun orphaned forever.

import logging

from django.utils import timezone

from initiatives.models import ActionRunStatus
from mixtape.celery_app import app as celery_app

logger = logging.getLogger(__name__)


class SwitchboardUnavailable(Exception):
    """Raised by callers that need an exception rather than a bool to propagate dispatch failure."""


def enqueue_switchboard_task(task_name, *, kwargs, action_run, queue="switchboard", **send_task_kwargs):
    """
    Send a Celery task to Switchboard's queue. Returns True on success.

    On a broker-level failure (unreachable, connection refused, etc.),
    marks `action_run` FAILED with a clear, user-visible reason and
    returns False -- callers should return a 503 rather than letting the
    exception propagate into an unhandled 500.
    """
    try:
        celery_app.send_task(task_name, kwargs=kwargs, queue=queue, **send_task_kwargs)
    except Exception as exc:
        logger.warning(
            "Switchboard dispatch failed for %s (action_run=%s): %s",
            task_name,
            action_run.id,
            exc,
        )
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": "switchboard_unavailable", "detail": str(exc)[:500]}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        return False
    return True


SWITCHBOARD_UNAVAILABLE_DETAIL = "Switchboard is temporarily unavailable. Please try again shortly."
