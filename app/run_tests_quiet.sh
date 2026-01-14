#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".env.test" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.test
  set +a
fi

export DJANGO_SETTINGS_MODULE=mixtape.settings.test
PYTHON="REDACTED-LOCAL-PATH/mixtape-release-core/env/bin/python"

LOG_DIR="$(mktemp -d -t mixtape-tests)"
echo "logs: ${LOG_DIR}"
echo "TEST_DB_NAME=${TEST_DB_NAME:-}"
echo "TEST_DB_USER=${TEST_DB_USER:-}"
echo "TEST_DB_PASSWORD=${TEST_DB_PASSWORD:-}"
echo "TEST_DB_HOST=${TEST_DB_HOST:-}"
echo "TEST_DB_PORT=${TEST_DB_PORT:-}"
echo "DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}"

./reset_test_db.sh
${PYTHON} manage.py migrate >"${LOG_DIR}/migrate.log" 2>&1

tests=(
  "stackroom.tests.test_collection_views"
  "stackroom.tests.test_collection_serializers stackroom.tests.test_library_item_model"
  "stackroom.tests.test_puddlejump_api"
  "stackroom.tests.test_puddlejump_phase2_api"
)

passed=0
failed=0

for test_cmd in "${tests[@]}"; do
  slug="${test_cmd// /_}"
  log_file="${LOG_DIR}/${slug}.log"
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
