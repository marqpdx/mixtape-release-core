#!/usr/bin/env bash
# ./stop_celery_all_local.sh
# Stop the local Celery stack for this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CELERY_BIN="$SCRIPT_DIR/env/bin/celery"

patterns=(
  "$CELERY_BIN -A mixtape.celery_app beat"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n local-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n push-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n commons-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n synopsis-results-worker@"
  # Legacy Core-owned Switchboard processes only. The standalone worker uses
  # a different Python/Celery app command and is not matched by these patterns.
  "$CELERY_BIN -A mixtape.celery_app worker .* -n switchboard-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n transcription-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n ocr-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n catalyst-worker@"
  "$CELERY_BIN -A mixtape.celery_app worker .* -n polling-worker@"
  "bash ./run_celery_beat_local.sh"
  "bash ./run_celery_local.sh"
  "bash ./run_celery_push_local.sh"
  "bash ./run_celery_commons_local.sh"
  "bash ./run_celery_synopsis_results_local.sh"
  "bash ./run_celery_switchboard_local.sh"
  "bash ./run_celery_transcription_local.sh"
  "bash ./run_celery_ocr_local.sh"
  "bash ./run_celery_catalyst_local.sh"
  "bash ./run_celery_polling_local.sh"
  "bash ./run_celery_all_local.sh"
)

find_pids() {
  local pattern="$1"
  pgrep -f "$pattern" 2>/dev/null || true
}

collect_pids() {
  local seen="" pid pattern

  for pattern in "${patterns[@]}"; do
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      [[ "$pid" == "$$" ]] && continue
      if [[ " $seen " != *" $pid "* ]]; then
        printf '%s\n' "$pid"
        seen+=" $pid"
      fi
    done < <(find_pids "$pattern")
  done
}

read_pids() {
  local target_name="$1" pid
  eval "$target_name=()"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    eval "$target_name+=(\"\$pid\")"
  done < <(collect_pids)
}

read_pids pids

if ((${#pids[@]} == 0)); then
  echo "[celery-stop] no local Celery processes found for this repo."
  exit 0
fi

echo "[celery-stop] stopping ${#pids[@]} local Celery process(es): ${pids[*]}"
kill "${pids[@]}" 2>/dev/null || true

sleep 3

read_pids remaining
if ((${#remaining[@]})); then
  echo "[celery-stop] forcing ${#remaining[@]} remaining process(es): ${remaining[*]}"
  kill -TERM "${remaining[@]}" 2>/dev/null || true
  sleep 2
fi

read_pids remaining
if ((${#remaining[@]})); then
  echo "[celery-stop] still running after TERM: ${remaining[*]}" >&2
  exit 1
fi

echo "[celery-stop] stopped."
