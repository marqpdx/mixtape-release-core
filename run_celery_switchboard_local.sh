#!/usr/bin/env bash
# ./run_celery_switchboard_local.sh
# Compatibility wrapper. Switchboard owns and runs its Celery worker.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SWITCHBOARD_RUNNER="$SCRIPT_DIR/../mixtape-release-switchboard/run_switchboard_worker.sh"

if [[ ! -x "$SWITCHBOARD_RUNNER" ]]; then
  echo "Missing Switchboard worker runner at $SWITCHBOARD_RUNNER" >&2
  exit 1
fi

echo "[deprecated] Core no longer owns the Switchboard worker; forwarding to mixtape-release-switchboard."
exec "$SWITCHBOARD_RUNNER"
