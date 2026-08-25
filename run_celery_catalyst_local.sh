#!/usr/bin/env bash
# ./run_celery_catalyst_local.sh
# Dedicated worker for the catalyst queue.
# Catalyst parse jobs spawn claude -p subprocesses that block 3-4 min per file.
# Isolated here so long-running jobs don't starve push notifications or email tasks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
CELERY_QUEUES=catalyst \
CELERY_NODE_NAME=catalyst-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
