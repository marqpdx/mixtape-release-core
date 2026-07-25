# projects/services.py

from datetime import date, timedelta

from projects.models import TaskSeverity, TaskTimeliness


def enforce_critical_rule(severity: str, timeliness: str) -> str:
    """Critical severity forces timeliness to Pressing — no exceptions."""
    if severity == TaskSeverity.CRITICAL:
        return TaskTimeliness.PRESSING
    return timeliness


def compute_due_date(severity: str, timeliness: str) -> date:
    """
    Auto-calculate due date from severity + timeliness.

    Critical → today (now-level incident).
    Pressing → tomorrow.
    Normal   → one week.
    Eventually → one month.
    """
    today = date.today()
    if severity == TaskSeverity.CRITICAL:
        return today
    if timeliness == TaskTimeliness.PRESSING:
        return today + timedelta(days=1)
    if timeliness == TaskTimeliness.NORMAL:
        return today + timedelta(weeks=1)
    # Eventually
    return today + timedelta(days=30)
