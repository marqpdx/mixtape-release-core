#!/usr/bin/env bash
# ./run_celery_commons_local.sh
# Dedicated worker for the commons queue (URL extraction via Inkwell).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
CELERY_QUEUES=commons \
CELERY_NODE_NAME=commons-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
