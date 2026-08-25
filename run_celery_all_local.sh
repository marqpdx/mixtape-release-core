#!/usr/bin/env bash
# ./run_celery_all_local.sh
# Start the full local Celery stack in dependency-safe order.
#
# Order:
#   1. Workers first, so queues have consumers before beat starts enqueueing.
#   2. Beat last, and exactly once.
set -euo pipefail
set +m

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/.local/celery/logs"
mkdir -p "$LOG_DIR"

RUNNER_PIDS=()
TAIL_PIDS=()
NAMES=()

cleanup() {
  local code=$?
  local child_pids
  trap - INT TERM EXIT

  child_pids="$(pgrep -P "$$" 2>/dev/null || true)"
  if [[ -n "$child_pids" ]]; then
    kill $child_pids 2>/dev/null || true
  fi

  if ((${#RUNNER_PIDS[@]})); then
    echo
    echo "[celery-all] stopping ${#RUNNER_PIDS[@]} Celery runner(s)..."
    for pid in "${RUNNER_PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      fi
    done

    sleep 2

    for pid in "${RUNNER_PIDS[@]}"; do
      if kill -0 "$pid" 2>/dev/null; then
        kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
      fi
    done
  fi

  "$SCRIPT_DIR/stop_celery_all_local.sh" >/dev/null 2>&1 || true

  child_pids="$(pgrep -P "$$" 2>/dev/null || true)"
  if [[ -n "$child_pids" ]]; then
    kill $child_pids 2>/dev/null || true
  fi

  echo "[celery-all] stopped."

  exit "$code"
}

trap cleanup INT TERM EXIT

start_runner() {
  local name="$1"
  local script="$2"
  local log="$LOG_DIR/$name.log"

  if [[ ! -x "$SCRIPT_DIR/$script" ]]; then
    echo "[celery-all] missing executable: $script" >&2
    exit 1
  fi

  : > "$log"
  echo "[celery-all] starting $name -> $script"
  (
    cd "$SCRIPT_DIR"
    if command -v setsid >/dev/null 2>&1; then
      exec setsid "./$script" >"$log" 2>&1
    fi
    exec "./$script" >"$log" 2>&1
  ) &

  RUNNER_PIDS+=("$!")
  NAMES+=("$name")
}

assert_alive() {
  local name="$1"
  local pid="$2"

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[celery-all] $name exited during startup. Last log lines:" >&2
    tail -40 "$LOG_DIR/$name.log" >&2 || true
    exit 1
  fi
}

# Workers: light/fast queues first, heavier and polling queues after. Beat is last.
start_runner "default" "run_celery_local.sh"
start_runner "push" "run_celery_push_local.sh"
start_runner "commons" "run_celery_commons_local.sh"
start_runner "synopsis_results" "run_celery_synopsis_results_local.sh"
start_runner "switchboard" "run_celery_switchboard_local.sh"
start_runner "transcription" "run_celery_transcription_local.sh"
start_runner "ocr" "run_celery_ocr_local.sh"
start_runner "catalyst" "run_celery_catalyst_local.sh"
start_runner "polling" "run_celery_polling_local.sh"

sleep 3
for i in "${!RUNNER_PIDS[@]}"; do
  assert_alive "${NAMES[$i]}" "${RUNNER_PIDS[$i]}"
done

start_runner "beat" "run_celery_beat_local.sh"
sleep 2
last_index=$((${#RUNNER_PIDS[@]} - 1))
assert_alive "beat" "${RUNNER_PIDS[$last_index]}"

echo
echo "[celery-all] all runners started. Logs: $LOG_DIR"
echo "[celery-all] press Ctrl+C to stop the full local Celery stack."
echo

for name in "${NAMES[@]}"; do
  tail -n 0 -F "$LOG_DIR/$name.log" 2>/dev/null | sed -u "s/^/[$name] /" &
  TAIL_PIDS+=("$!")
done

while true; do
  sleep 3600 &
  wait "$!" || true
done
