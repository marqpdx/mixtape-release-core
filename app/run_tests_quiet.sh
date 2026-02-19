#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ -f ".env.test" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.test
  set +a
fi

export DJANGO_SETTINGS_MODULE=mixtape.settings.test
PYTHON="REDACTED-LOCAL-PATH/mixtape-release-core/env/bin/python"
PIP="REDACTED-LOCAL-PATH/mixtape-release-core/env/bin/pip"

LOG_DIR="$(mktemp -d -t mixtape-tests)"
echo "logs: ${LOG_DIR}"
echo "TEST_DB_NAME=${TEST_DB_NAME:-}"
echo "TEST_DB_USER=${TEST_DB_USER:-}"
echo "TEST_DB_PASSWORD=${TEST_DB_PASSWORD:-}"
echo "TEST_DB_HOST=${TEST_DB_HOST:-}"
echo "TEST_DB_PORT=${TEST_DB_PORT:-}"
echo "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"
if [[ "${CODEX_SANDBOX_NETWORK_DISABLED:-}" == "1" ]]; then
  echo "note: CODEX sandbox network is disabled; DB connections to ${TEST_DB_HOST:-localhost}:${TEST_DB_PORT:-} may fail unless you rerun with elevated permissions."
fi

REQ_FILE="${ROOT_DIR}/requirements-dev.txt"
if [[ ! -f "${REQ_FILE}" ]]; then
  echo "missing ${REQ_FILE}; update run_tests_quiet.sh to point at the correct requirements file"
  exit 1
fi
${PIP} install -r "${REQ_FILE}" >"${LOG_DIR}/pip_install.log" 2>&1
./reset_test_db.sh
${PYTHON} manage.py migrate >"${LOG_DIR}/migrate.log" 2>&1

tests=(
  "stackroom.tests.test_collection_views"
  "stackroom.tests.test_collection_serializers stackroom.tests.test_library_item_model"
  "stackroom.tests.test_puddlejump_api"
  "stackroom.tests.test_puddlejump_phase2_api"
  "stackroom.tests.test_library_publish_shelves"
  "stackroom.tests.test_puddlejump_utilities_api"
  "concord.tests.test_recording_api concord.tests.test_recording_models concord.tests.test_session_models concord.tests.test_speaker_anchor_models concord.tests.test_transcription_models"
  "groups.tests"
  "lists"
  "dispatch.tests"
  "projects.tests"
  "public_api.tests"
  "publishing.tests"
  "writing.tests"
)

passed=0
failed=0

selected_tests=()
run_all=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --all)
      run_all=1
      shift
      ;;
    *)
      selected_tests+=("$1")
      shift
      ;;
  esac
done

if [[ ${#selected_tests[@]} -gt 0 ]]; then
  tests=("${selected_tests[@]}")
elif [[ $run_all -eq 1 ]]; then
  tests=("")
fi

for test_cmd in "${tests[@]}"; do
  slug="${test_cmd// /_}"
  if [[ -z "${slug}" ]]; then
    slug="all_tests"
  fi
  log_file="${LOG_DIR}/${slug}.log"
  if [[ -z "${test_cmd}" ]]; then
    echo "running all tests"
    if ${PYTHON} manage.py test --noinput --keepdb >"${log_file}" 2>&1; then
      echo "running all tests pass"
      passed=$((passed + 1))
    else
      echo "running all tests failed"
      failed=$((failed + 1))
    fi
    continue
  fi
  echo "running ${test_cmd}"
  if ${PYTHON} manage.py test ${test_cmd} --noinput --keepdb >"${log_file}" 2>&1; then
    echo "running ${test_cmd} pass"
    passed=$((passed + 1))
  else
    echo "running ${test_cmd} failed"
    failed=$((failed + 1))
  fi
done

total=$((passed + failed))
echo "${passed} of ${total} test runs passed"
