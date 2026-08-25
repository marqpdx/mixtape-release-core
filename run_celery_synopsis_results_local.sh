#!/usr/bin/env bash
# ./run_celery_synopsis_results_local.sh
# Dedicated worker for FastAPI -> Django synopsis result callbacks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
CELERY_QUEUES=synopsis_results \
CELERY_NODE_NAME=synopsis-results-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
