#!/usr/bin/env bash
# ./run_celery_local.sh
set -euo pipefail

# repo root is the directory of this script
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# venv
source "$REPO_ROOT/env/bin/activate"

# Find project root (directory that contains manage.py)
if [ -f "$REPO_ROOT/app/manage.py" ]; then
  APP_ROOT="$REPO_ROOT/app"
else
  # fallback: search one level deep
  APP_ROOT="$(dirname "$(find "$REPO_ROOT" -maxdepth 2 -name manage.py -print -quit)")"
fi

if [ ! -f "$APP_ROOT/manage.py" ]; then
  echo "❌ Could not find manage.py. Set APP_ROOT manually."
  exit 1
fi

cd "$APP_ROOT"

# Project package (adjust if different)
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.dev}"

# Ensure Python can import from APP_ROOT
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:${PYTHONPATH}}"

# Queue from env (fallback dev_queue)
export CELERY_TASK_DEFAULT_QUEUE="${CELERY_TASK_DEFAULT_QUEUE:-dev_queue}"

echo "📁 APP_ROOT: $APP_ROOT"
echo "⚙️  DJANGO_SETTINGS_MODULE: $DJANGO_SETTINGS_MODULE"
echo "🧩 PYTHONPATH: $PYTHONPATH"
echo "📬 Queue: $CELERY_TASK_DEFAULT_QUEUE"

# Start worker
celery -A mixtape.celery_app worker \
  --loglevel=info \
  --concurrency=5 \
  --prefetch-multiplier=5 \
  -Q "$CELERY_TASK_DEFAULT_QUEUE" \
  -n release-worker@%h
