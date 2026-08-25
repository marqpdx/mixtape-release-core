#!/usr/bin/env bash
# ./run_celery_switchboard_local.sh
# Dedicated worker for the Switchboard AI task queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
CELERY_QUEUES=switchboard \
CELERY_NODE_NAME=switchboard-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
