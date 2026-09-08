#!/usr/bin/env bash
set -u

BASE_URL="${BASE_URL:-http://localhost:8000}"
GROUP_SLUG="${GROUP_SLUG:-${1:-}}"
AUTH_HEADER="${AUTH_HEADER:-}"
CONTENT_TYPE="Content-Type: application/json"

if [ -z "$GROUP_SLUG" ]; then
  printf "usage: GROUP_SLUG=<slug> %s\n" "$0"
  printf "optional: BASE_URL=http://localhost:8000 AUTH_HEADER='Authorization: Bearer <token>' START_LOGIN=1 LOGOUT=1\n"
  exit 2
fi

LOG_DIR="${LOG_DIR:-$(mktemp -d -t mixtape-codex-api)}"
passed=0
failed=0
skipped=0

print_header() {
  printf "\n== %s ==\n" "$1"
}

request() {
  name="$1"
  method="$2"
  path="$3"
  data="${4:-}"
  expected="${5:-}"
  log_name="$(printf "%s" "$name" | tr ' /:' '____')"
  body_file="${LOG_DIR}/${log_name}.body.json"
  meta_file="${LOG_DIR}/${log_name}.meta.txt"
  headers_file="${LOG_DIR}/${log_name}.headers.txt"

  printf "\n[%s]\n" "$name"
  printf "request: %s %s%s\n" "$method" "$BASE_URL" "$path"
  printf "body: %s\n" "$body_file"

  curl_cmd=(curl -sS -X "$method")
  if [ -n "$AUTH_HEADER" ]; then
    curl_cmd+=(-H "$AUTH_HEADER")
  fi
  curl_cmd+=(-D "$headers_file" -o "$body_file" -w "%{http_code}")

  if [ -n "$data" ]; then
    curl_cmd+=(-H "$CONTENT_TYPE" --data "$data")
    status="$("${curl_cmd[@]}" "${BASE_URL}${path}" 2>"$meta_file")"
  else
    status="$("${curl_cmd[@]}" "${BASE_URL}${path}" 2>"$meta_file")"
  fi

  if [ -s "$meta_file" ]; then
    printf "curl stderr:\n"
    cat "$meta_file"
  fi

  printf "status: %s\n" "$status"
  if [ -n "$expected" ] && [ "$status" != "$expected" ]; then
    printf "result: FAIL, expected HTTP %s\n" "$expected"
    printf "response preview:\n"
    head -c 1200 "$body_file"
    printf "\n"
    failed=$((failed + 1))
    return 1
  fi

  printf "result: PASS\n"
  passed=$((passed + 1))
}

print_header "Codex Runtime API Smoke"
printf "base url: %s\n" "$BASE_URL"
printf "group slug: %s\n" "$GROUP_SLUG"
printf "logs: %s\n" "$LOG_DIR"
if [ -z "$AUTH_HEADER" ]; then
  printf "auth: none supplied; admin-only endpoints should reject or redirect\n"
else
  printf "auth: supplied\n"
fi

request "codex runtime status" GET "/api/tenant-runtime/groups/${GROUP_SLUG}/codex/status/" "" "${STATUS_EXPECTED:-200}"

if [ "${START_LOGIN:-0}" = "1" ]; then
  request "start codex login" POST "/api/tenant-runtime/groups/${GROUP_SLUG}/codex/start-login/" "{}" "${START_LOGIN_EXPECTED:-202}"
  request "codex login status after start" GET "/api/tenant-runtime/groups/${GROUP_SLUG}/codex/login-status/" "" "${LOGIN_STATUS_EXPECTED:-200}"
else
  print_header "Start Login"
  printf "result: SKIP\n"
  printf "set START_LOGIN=1 to POST the login start endpoint\n"
  skipped=$((skipped + 1))
fi

if [ "${LOGOUT:-0}" = "1" ]; then
  request "codex logout" POST "/api/tenant-runtime/groups/${GROUP_SLUG}/codex/logout/" "{}" "${LOGOUT_EXPECTED:-200}"
else
  print_header "Logout"
  printf "result: SKIP\n"
  printf "set LOGOUT=1 to POST the logout endpoint\n"
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
