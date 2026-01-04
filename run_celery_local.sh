#!/usr/bin/env bash
# ./run_celery_local.sh
set -euo pipefail

# --- locate repo + app root ---
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${APP_ROOT:-}"

if [[ -z "${APP_ROOT}" ]]; then
  if [[ -f "$REPO_ROOT/app/manage.py" ]]; then
    APP_ROOT="$REPO_ROOT/app"
  else
    APP_ROOT="$(dirname "$(find "$REPO_ROOT" -maxdepth 2 -name manage.py -print -quit || true)")"
  fi
fi

if [[ ! -f "$APP_ROOT/manage.py" ]]; then
  echo "❌ Could not find manage.py (APP_ROOT=$APP_ROOT). Set APP_ROOT and retry."
  exit 1
fi

# --- venv ---
if [[ ! -f "$REPO_ROOT/env/bin/activate" ]]; then
  echo "❌ venv not found at $REPO_ROOT/env. Create it first."
  exit 1
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/env/bin/activate"

# --- load .env (optional) ---
if [[ -f "$REPO_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

cd "$APP_ROOT"

# --- Django + Python path ---
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.dev}"
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# --- CRITICAL: Force PyTorch CPU-only mode (prevents MPS crashes) ---
export PYTORCH_ENABLE_MPS_FALLBACK=0
export CUDA_VISIBLE_DEVICES=""
export OMP_NUM_THREADS=4

# --- queue naming (your new shared env) ---
export SHARED_RABBIT_CHAT_QUEUE="${SHARED_RABBIT_CHAT_QUEUE:-mixtape_shared_rabbit_chat_queue_stage}"

# --- show config snapshot ---
echo "📁 APP_ROOT:               $APP_ROOT"
echo "⚙️  DJANGO_SETTINGS_MODULE: $DJANGO_SETTINGS_MODULE"
echo "🧩 PYTHONPATH:             $PYTHONPATH"
echo "📬 Queue (consume):        $SHARED_RABBIT_CHAT_QUEUE"
echo "🐰 Broker:                 ${CELERY_BROKER_URL:-<not set>}"

# --- run worker ---
exec celery -A mixtape.celery_app worker \
  --loglevel=info \
  --concurrency=5 \
  --prefetch-multiplier=5 \
  -Q "$SHARED_RABBIT_CHAT_QUEUE" \
  -n local-worker@%h





# #!/usr/bin/env bash
# # ./run_celery_local.sh
# set -euo pipefail

# # repo root is the directory of this script
# REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# # venv
# source "$REPO_ROOT/env/bin/activate"

# # Find project root (directory that contains manage.py)
# if [ -f "$REPO_ROOT/app/manage.py" ]; then
#   APP_ROOT="$REPO_ROOT/app"
# else
#   # fallback: search one level deep
#   APP_ROOT="$(dirname "$(find "$REPO_ROOT" -maxdepth 2 -name manage.py -print -quit)")"
# fi

# if [ ! -f "$APP_ROOT/manage.py" ]; then
#   echo "❌ Could not find manage.py. Set APP_ROOT manually."
#   exit 1
# fi

# cd "$APP_ROOT"

# # Project package (adjust if different)
# export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.dev}"

# # Ensure Python can import from APP_ROOT
# export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:${PYTHONPATH}}"

# # Queue from env (fallback dev_queue)
# export SHARED_RABBIT_CHAT_QUEUE="${CELERY_TASK_DEFAULT_QUEUE:-stage_queue}"

# echo "📁 APP_ROOT: $APP_ROOT"
# echo "⚙️  DJANGO_SETTINGS_MODULE: $DJANGO_SETTINGS_MODULE"
# echo "🧩 PYTHONPATH: $PYTHONPATH"
# echo "📬 Queue: $CELERY_TASK_DEFAULT_QUEUE"

# # Start worker
# celery -A mixtape worker \
#   --loglevel=info \
#   --concurrency=5 \
#   --prefetch-multiplier=5 \
#   -Q "$CELERY_TASK_DEFAULT_QUEUE" \
#   -n release-worker@%h
