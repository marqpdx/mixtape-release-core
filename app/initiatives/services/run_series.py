# initiatives/services/run_series.py
#
# ADR-0064 D9: finding which run series are due, and closing out ones whose
# span has elapsed. Starting a due run is a separate step (AC-5's
# argus.start_run path to Cass's Switchboard) -- this module only decides
# "due or not", so it has no server/network dependency and is exercised
# by model-only tests.

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from initiatives.models import RunSeries, RunSeriesSpanKind, RunSeriesStatus


def close_elapsed_series(now=None) -> list[RunSeries]:
    """Mark COMPLETED any ACTIVE series whose span has run out. Returns the ones closed."""
    now = now or timezone.now()
    closed = []
    for rs in RunSeries.objects.filter(status=RunSeriesStatus.ACTIVE):
        elapsed_days = rs.span_kind == RunSeriesSpanKind.DAYS and (now - rs.created_at) > timedelta(days=rs.span_value)
        elapsed_runs = rs.span_kind == RunSeriesSpanKind.RUNS and rs.runs_done >= rs.span_value
        if elapsed_days or elapsed_runs:
            rs.status = RunSeriesStatus.COMPLETED
            rs.save(update_fields=["status", "updated_at"])
            closed.append(rs)
    return closed


def due_run_series(now=None) -> list[RunSeries]:
    """
    ACTIVE series (after closing elapsed ones) whose cadence has come due,
    measured from the last run's start, or the series' own creation if it
    has never run yet. D9's "one run at a time on Cass" is enforced by the
    runner, not here -- this is just "which series want a run right now".
    """
    now = now or timezone.now()
    close_elapsed_series(now=now)

    due = []
    for rs in RunSeries.objects.filter(status=RunSeriesStatus.ACTIVE):
        last_run = rs.action_runs.order_by("-started_at").first()
        reference = last_run.started_at if last_run else rs.created_at
        if now - reference >= timedelta(hours=rs.cadence_hours):
            due.append(rs)
    return due
