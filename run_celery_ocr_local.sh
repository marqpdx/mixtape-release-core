#!/usr/bin/env bash
# ./run_celery_ocr_local.sh
# Dedicated worker for the OCR spike queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=prefork \
CELERY_CONCURRENCY=1 \
CELERY_QUEUES=ocr \
CELERY_NODE_NAME=ocr-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
