#!/bin/bash

# ./run_celery_local.sh

# Navigate to the directory where manage.py lives
source "$(dirname "$0")/env/bin/activate"

cd "$(dirname "$0")/app"

echo "🔄 Starting Celery worker for RELEASE repo..."
PYTHONPATH=$(pwd) \
DJANGO_SETTINGS_MODULE=mixtape.settings.dev \
../env/bin/celery -A mixtape worker \
  --loglevel=info \
  -E \
  --concurrency=5 \
  --prefetch-multiplier=5 \
  -n release-worker@%h

