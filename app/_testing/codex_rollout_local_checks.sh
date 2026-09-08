#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-${APP_DIR}/../env/bin/python}"
RUFF="${RUFF:-${APP_DIR}/../env/bin/ruff}"
LOG_DIR="${LOG_DIR:-$(mktemp -d -t mixtape-codex-rollout)}"

cd "$APP_DIR"

if [ -f ".env.test" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.test"
  set +a
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-mixtape.settings.test}"

passed=0
failed=0
skipped=0

print_header() {
  printf "\n== %s ==\n" "$1"
}

run_check() {
  name="$1"
  shift
  log_name="$(printf "%s" "$name" | tr ' /:' '____')"
  log_file="${LOG_DIR}/${log_name}.log"

  printf "\n[%s]\n" "$name"
  printf "command: %s\n" "$*"
  printf "log: %s\n" "$log_file"

  if "$@" >"$log_file" 2>&1; then
    printf "result: PASS\n"
    passed=$((passed + 1))
  else
    printf "result: FAIL\n"
    printf "last output:\n"
    tail -n 40 "$log_file"
    failed=$((failed + 1))
  fi
}

run_optional_check() {
  name="$1"
  binary="$2"
  shift 2

  if [ ! -x "$binary" ]; then
    printf "\n[%s]\n" "$name"
    printf "result: SKIP (%s not executable)\n" "$binary"
    skipped=$((skipped + 1))
    return
  fi

  run_check "$name" "$binary" "$@"
}

print_header "Codex Rollout Local Checks"
printf "app: %s\n" "$APP_DIR"
printf "python: %s\n" "$PYTHON"
printf "settings: %s\n" "$DJANGO_SETTINGS_MODULE"
printf "logs: %s\n" "$LOG_DIR"

run_check "django system check" "$PYTHON" manage.py check
run_check "provider dispatch and deterministic service tests" "$PYTHON" manage.py test codex.tests.test_service atrium.tests.test_ai_service claude.tests.test_service.TestRunBlocking claude.tests.test_service.TestStreamJsonSession --noinput
run_check "migration drift check" "$PYTHON" manage.py makemigrations --check --dry-run
run_optional_check "ruff critical checks" "$RUFF" check --isolated --select F821,F841,B006,B007,C4,T201 cloud_agents codex tenant_runtime atrium
run_check "git diff whitespace check" git diff --check

if [ "${RUN_BROAD_REGRESSION:-0}" = "1" ]; then
  run_check "broad regression: tenant_runtime atrium claude codex" "$PYTHON" manage.py test tenant_runtime atrium claude codex --noinput
else
  print_header "Broad Regression"
  printf "result: SKIP\n"
  printf "set RUN_BROAD_REGRESSION=1 to run: manage.py test tenant_runtime atrium claude codex --noinput\n"
  skipped=$((skipped + 1))
fi

if [ "${RUN_LIVE_CLAUDE_STREAM:-0}" = "1" ]; then
  run_check "live claude streaming smoke" "$PYTHON" manage.py test claude.tests.test_service.TestStream --noinput
else
  print_header "Live Claude Streaming"
  printf "result: SKIP\n"
  printf "set RUN_LIVE_CLAUDE_STREAM=1 to require a logged-in Claude CLI and run the live streaming smoke\n"
  skipped=$((skipped + 1))
fi

if [ "${APPLY_MIGRATIONS:-0}" = "1" ]; then
  run_check "apply tenant_runtime migrations" "$PYTHON" manage.py migrate tenant_runtime
  run_check "apply atrium migrations" "$PYTHON" manage.py migrate atrium
else
  print_header "Migrations"
  printf "result: SKIP\n"
  printf "set APPLY_MIGRATIONS=1 to run app migrations after checks pass\n"
  skipped=$((skipped + 1))
fi

print_header "Summary"
printf "passed: %s\n" "$passed"
printf "failed: %s\n" "$failed"
printf "skipped: %s\n" "$skipped"
printf "logs: %s\n" "$LOG_DIR"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
