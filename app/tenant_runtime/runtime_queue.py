# tenant_runtime/runtime_queue.py
"""
Run a person-runtime task on the runtime worker, wherever it was sent (ST-3).

Only crossroads-celery-runtime may use sudo; every other worker runs with
NoNewPrivileges. Switchboard sends some tasks to the "catalyst" queue by name
(Shuttle's reading, LinkedIn copy). Rather than change Switchboard, such a task
calls forward_to_runtime() first: on any worker but the runtime worker it
re-sends itself there, unchanged, and returns. Called directly or eagerly
(tests), it runs in place.
"""

RUNTIME_QUEUE = "runtime"


def forward_to_runtime(task, *, args=None, kwargs=None) -> bool:
    """True when this call was handed to the runtime worker; the caller then returns."""
    request = task.request
    if getattr(request, "is_eager", False) or not getattr(request, "id", None):
        return False
    routing_key = (getattr(request, "delivery_info", None) or {}).get("routing_key")
    if routing_key in (None, "", RUNTIME_QUEUE):
        return False
    task.apply_async(args=args, kwargs=kwargs, queue=RUNTIME_QUEUE, routing_key=RUNTIME_QUEUE)
    return True
