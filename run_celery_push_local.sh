#!/usr/bin/env bash
# ./run_celery_push_local.sh
# Dedicated worker for the push queue (email, push notifications, asset uploads).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=2 \
SHARED_RABBIT_CHAT_QUEUE=push \
CELERY_NODE_NAME=push-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
