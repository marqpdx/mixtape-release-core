#!/usr/bin/env bash
set -euo pipefail

if [ -f ".env.test" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.test
  set +a
fi

export DJANGO_SETTINGS_MODULE=mixtape.settings.test
REDACTED-LOCAL-PATH/mixtape-release-core/env/bin/python manage.py reset_test_db --force
