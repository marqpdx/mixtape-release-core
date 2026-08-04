"""
TenantScopedTask — Celery base class enforcing explicit tenant identity.

Resolves FN-D5's previously open enforcement question: tasks that operate on
tenant-scoped data must declare group_id as an explicit kwarg. This class
validates that before task execution and raises if absent, converting a
silent data-leak risk into an immediate, loud failure.

Beat-scheduled tasks that operate cross-tenant by design (FN-D7 enumerated
list) must NOT inherit from this class — they use the standard Task base.
Those tasks are: dispatch_scheduled_broadcasts_task, recover_missed_publish_events,
publish_scheduled_pieces, collect_postgres_snapshot, collect_application_snapshot,
run_scheduled_snapshots, advance_recurring_actions, apply_memory_value_decay_task.

Usage:
    @shared_task(base=TenantScopedTask, name="groups.tasks.some_task")
    def some_task(group_id: str, ...) -> None:
        group = Group.objects.filter(pk=group_id, is_active=True).first()
        ...
"""
from celery import Task


class MissingTenantArgumentError(Exception):
    pass


class TenantScopedTask(Task):
    abstract = True

    def before_start(self, task_id, args, kwargs):
        if not kwargs.get("group_id"):
            raise MissingTenantArgumentError(
                f"TenantScopedTask '{self.name}' was dispatched without 'group_id' kwarg. "
                "Request-local tenant context is not available in Celery workers — "
                "pass group_id explicitly in every task dispatch."
            )
        super().before_start(task_id, args, kwargs)
