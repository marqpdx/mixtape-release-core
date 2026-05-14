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

# Keep the schema, clear the data. This is the stable built-in reset path for the
# shared test database and avoids relying on a custom management command.
${PYTHON} manage.py flush --noinput
