"""Complete a bounded interpretation; all subprocess execution uses the
shared runner. Thin Shuttle wiring over Heddle's generic task bodies
(ADR-0061, HD-2) — task names, queues and this module's path are
unchanged so Switchboard's existing dispatch and this module's own
tests keep working."""
from __future__ import annotations

from celery import shared_task

from heddle import tasks as heddle_tasks

from .contract import SHUTTLE_READING


@shared_task(name="shuttle.run_cloud_interpretation", queue="catalyst", soft_time_limit=210, time_limit=240)
def run_cloud_interpretation(*, action_run_id):
    heddle_tasks.run_cloud_interpretation(action_run_id=action_run_id, reading=SHUTTLE_READING,
        apply_fn=lambda child_id: apply_interpretation(child_id))


@shared_task(name="shuttle.apply_interpretation", queue="catalyst")
def apply_interpretation(action_run_id):
    heddle_tasks.apply_interpretation(action_run_id, reading=SHUTTLE_READING)
