# ai/task/startup.py

import logging


logger = logging.getLogger(__name__)

from celery import shared_task

from inkwell.scripts.startup import run_startup_tasks


@shared_task(name="ai.run_startup")
def run_startup_task_async(force=False):
    """
    Celery-compatible async wrapper for run_startup_tasks().
    Ensures proper lock guarding and can be safely called across workers.
    """
    logger.info("[celery] Temp Disabled: run_startup_task_async...")
    return
    try:
        logger.info("[celery] 🚀 Running run_startup_tasks(force={force}) via Celery...")
        run_startup_tasks(force=force)
        logger.info("[celery] ✅ run_startup_tasks completed")
    except Exception as e:
        logger.error("[celery]  run_startup_tasks failed: %s", e)
        raise e


