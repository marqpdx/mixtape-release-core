# Cross-process file lock

# Optional force=True override

# Auto-expiring lock (e.g., 10 minutes)

# Optional DB record or log file for traceability

# Works in both dev and prod


import logging


logger = logging.getLogger(__name__)

import time
from functools import wraps
from pathlib import Path


LOCK_DIR = Path("/tmp/cdoc_locks")
LOCK_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_EXPIRY_SECONDS = 600  # 10 minutes

def run_once_globally_filelock(lock_key: str, expiry_seconds=DEFAULT_EXPIRY_SECONDS):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, force=False, **kwargs):
            lockfile = LOCK_DIR / f"{lock_key}.lock"

            if lockfile.exists() and not force:
                try:
                    mtime = lockfile.stat().st_mtime
                    age = time.time() - mtime
                    if age < expiry_seconds:
                        logger.info("[startup] ⏭ Skipping {lock_key}, lock exists ({int(age)}s old).")
                        return None
                    logger.info("[startup]  Lock expired (%ss), re-running.", int(age))
                except Exception as e:
                    logger.warning("[startup]  Failed to stat lockfile: %s", e)

            try:
                with open(lockfile, "w") as f:
                    f.write(f"locked at {time.ctime()}\n")
                logger.info("[startup]  Lock created: %s", lockfile)
                return func(*args, **kwargs)
            finally:
                try:
                    lockfile.unlink()
                    logger.info("[startup]  Lock removed: %s", lockfile)
                except Exception as e:
                    logger.warning("[startup]  Could not remove lockfile: %s", e)

        return wrapper
    return decorator
