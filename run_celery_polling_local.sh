#!/usr/bin/env bash
# ./run_celery_polling_local.sh
# Dedicated worker for beat-scheduled polling tasks (stackroom, ownership, broadcasts).
# Isolated from the default worker so high-frequency polls don't flood logs
# or hold worker slots needed by push/activity tasks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
CELERY_PREFETCH_MULTIPLIER=1 \
CELERY_QUEUES=polling \
CELERY_NODE_NAME=polling-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
