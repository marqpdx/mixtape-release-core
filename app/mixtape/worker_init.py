"""
Celery worker initialization hooks.

This module sets up each worker process when it starts.
"""

import logging
import traceback as tb

from celery.signals import task_failure, worker_process_init

logger = logging.getLogger(__name__)


@task_failure.connect
def on_task_failure(sender, task_id, exception, args, kwargs, traceback, einfo, **extra):
    """
    Write a TaskFailureLog row whenever any Celery task fails after exhausting retries.
    Only fires on terminal failure, not on intermediate retries.
    """
    retries = getattr(sender.request, "retries", 0)
    max_retries = getattr(sender, "max_retries", None)
    if max_retries is not None and retries < max_retries:
        return

    try:
        from ops.models import TaskFailureLog
        TaskFailureLog.objects.create(
            task_name=sender.name,
            exception_type=type(exception).__name__,
            exception_message=str(exception),
            traceback="".join(tb.format_exception(type(exception), exception, traceback)),
            queue=getattr(sender.request, "delivery_info", {}).get("routing_key", ""),
            retries=retries,
        )
    except Exception as log_exc:
        logger.error("TaskFailureLog write failed: %s", log_exc)


@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Called when each worker process starts (after fork).

    This is where we need to patch torch to disable MPS,
    since each forked worker gets a fresh Python interpreter.
    """
    logger.info("🔧 Worker process initializing...")

    # Import and apply force_cpu patch
    try:
        import force_cpu
        force_cpu.patch_torch()  # Explicitly call patch
        # Skip patch_tqdm if fake tqdm module is already injected
        if getattr(force_cpu, "__file__", "") and "force_cpu.py" in force_cpu.__file__:
            import sys
            tqdm_module = sys.modules.get("tqdm")
            if tqdm_module and tqdm_module.__class__.__name__ == "FakeTqdm":
                logger.info("ℹ️  Worker process: Fake tqdm already injected, skipping patch_tqdm")
            else:
                force_cpu.patch_tqdm()   # Also patch tqdm to prevent threading issues
        else:
            force_cpu.patch_tqdm()
        logger.info("✅ Worker process: MPS disabled, CPU-only mode enforced")
    except Exception as e:
        # Don't crash the worker if patching fails - log warning and continue
        logger.warning(f"⚠️  Worker process: Failed to apply CPU patches: {e}")
        logger.warning("   Worker will continue but may encounter MPS-related issues")
