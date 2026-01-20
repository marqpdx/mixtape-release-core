#!/usr/bin/env bash
# ./run_celery_beat_local.sh
set -euo pipefail

# Run Celery beat with dev environment for consistent routing
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$SCRIPT_DIR/env/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/env/bin/activate"
fi

export DJANGO_ENV=dev
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.dev}"

cd "$SCRIPT_DIR/app"

exec celery -A mixtape.celery_app beat --loglevel=info
