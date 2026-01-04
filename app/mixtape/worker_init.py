"""
Celery worker initialization hooks.

This module sets up each worker process when it starts.
"""

import logging
from celery.signals import worker_process_init

logger = logging.getLogger(__name__)


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
        force_cpu.patch_tqdm()   # Also patch tqdm to prevent threading issues
        logger.info("✅ Worker process: MPS disabled, CPU-only mode enforced")
    except Exception as e:
        # Don't crash the worker if patching fails - log warning and continue
        logger.warning(f"⚠️  Worker process: Failed to apply CPU patches: {e}")
        logger.warning("   Worker will continue but may encounter MPS-related issues")
