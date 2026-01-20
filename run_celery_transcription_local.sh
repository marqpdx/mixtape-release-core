#!/usr/bin/env bash
# ./run_celery_transcription_local.sh
set -euo pipefail

# Run a dedicated transcription worker (solo pool) to avoid torch fork issues
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CELERY_POOL=solo \
CELERY_CONCURRENCY=1 \
SHARED_RABBIT_CHAT_QUEUE=transcription \
CELERY_NODE_NAME=transcription-worker@%h \
"$SCRIPT_DIR/run_celery_local.sh"
