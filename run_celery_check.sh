#!/usr/bin/env bash
# ./run_celery_check.sh
# Read-only sanity check for local Celery routing and beat configuration.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$REPO_ROOT/env/bin/activate" ]]; then
  echo "❌ venv not found at $REPO_ROOT/env. Create it first."
  exit 1
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/env/bin/activate"

APP_ROOT="$REPO_ROOT/app"
if [[ ! -f "$APP_ROOT/manage.py" ]]; then
  echo "❌ Could not find manage.py at $APP_ROOT/manage.py."
  exit 1
fi

cd "$APP_ROOT"

export DJANGO_ENV="${DJANGO_ENV:-dev}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.dev}"
export PYTHONPATH="$APP_ROOT${PYTHONPATH:+:${PYTHONPATH}}"

python - <<'PY'
from mixtape.celery_app import app

print("Default queue:", app.conf.task_default_queue)
print("Declared queues:", ", ".join(q.name for q in app.conf.task_queues))
print("\nBeat schedule:")
for name, entry in sorted(app.conf.beat_schedule.items()):
    print(f"  {name}: {entry['task']} every {entry['schedule']}s")

print("\nExplicit task routes:")
for name, route in sorted(app.conf.task_routes.items()):
    print(f"  {name}: {route['queue']}")
PY
