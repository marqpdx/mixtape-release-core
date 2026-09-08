#!/usr/bin/env bash
set -u

TENANT_USER="${TENANT_USER:-${1:-}}"
TENANT_HOME="${TENANT_HOME:-}"
CODEX_BIN="${CODEX_BIN:-codex}"
PROMPT="${PROMPT:-Reply exactly: OK}"

if [ -z "$TENANT_USER" ]; then
  printf "usage: TENANT_USER=<linux_user> %s\n" "$0"
  printf "optional: TENANT_HOME=/home/<linux_user> START_LOGIN=1 OTHER_USER=<linux_user> CODEX_BIN=/path/to/codex\n"
  exit 2
fi

if [ -z "$TENANT_HOME" ]; then
  TENANT_HOME="/home/${TENANT_USER}"
fi

CODEX_HOME="${CODEX_HOME:-${TENANT_HOME}/.codex}"
WORK_DIR="${WORK_DIR:-$TENANT_HOME}"
LOG_DIR="${LOG_DIR:-$(mktemp -d -t mixtape-codex-tenant)}"
LOGIN_STORE_CONFIG='cli_auth_credentials_store="file"'

passed=0
failed=0
skipped=0

print_header() {
  printf "\n== %s ==\n" "$1"
}

have_run_as() {
  command -v runuser >/dev/null 2>&1 || command -v sudo >/dev/null 2>&1
}

run_as_tenant() {
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$TENANT_USER" -- env HOME="$TENANT_HOME" CODEX_HOME="$CODEX_HOME" PATH="/usr/local/bin:/usr/bin:/bin" "$@"
  else
    sudo -u "$TENANT_USER" env HOME="$TENANT_HOME" CODEX_HOME="$CODEX_HOME" PATH="/usr/local/bin:/usr/bin:/bin" "$@"
  fi
}

run_as_other() {
  other_user="$1"
  shift
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$other_user" -- env HOME="/home/${other_user}" PATH="/usr/local/bin:/usr/bin:/bin" "$@"
  else
    sudo -u "$other_user" env HOME="/home/${other_user}" PATH="/usr/local/bin:/usr/bin:/bin" "$@"
  fi
}

record_check() {
  name="$1"
  shift
  log_name="$(printf "%s" "$name" | tr ' /:' '____')"
  log_file="${LOG_DIR}/${log_name}.log"

  printf "\n[%s]\n" "$name"
  printf "log: %s\n" "$log_file"

  if "$@" >"$log_file" 2>&1; then
    printf "result: PASS\n"
    passed=$((passed + 1))
    return 0
  fi

  printf "result: FAIL\n"
  tail -n 40 "$log_file"
  failed=$((failed + 1))
  return 1
}

print_header "Codex Tenant User Probe"
printf "tenant user: %s\n" "$TENANT_USER"
printf "tenant home: %s\n" "$TENANT_HOME"
printf "codex home: %s\n" "$CODEX_HOME"
printf "work dir: %s\n" "$WORK_DIR"
printf "logs: %s\n" "$LOG_DIR"

if ! have_run_as; then
  printf "result: FAIL\n"
  printf "runuser or sudo is required to execute as the tenant user\n"
  exit 1
fi

record_check "codex binary visible to tenant" run_as_tenant "$CODEX_BIN" --version

if [ "${START_LOGIN:-0}" = "1" ]; then
  print_header "Device Login"
  printf "Starting interactive device login. Follow the printed URL/code in your terminal.\n"
  printf "This command can run until the browser/device flow completes or the CLI times out.\n"
  run_as_tenant "$CODEX_BIN" login --device-auth -c "$LOGIN_STORE_CONFIG"
  login_exit=$?
  if [ "$login_exit" -eq 0 ]; then
    printf "device login result: PASS\n"
    passed=$((passed + 1))
  else
    printf "device login result: FAIL (%s)\n" "$login_exit"
    failed=$((failed + 1))
  fi
else
  print_header "Device Login"
  printf "result: SKIP\n"
  printf "set START_LOGIN=1 when the tenant user needs first-time ChatGPT auth\n"
  skipped=$((skipped + 1))
fi

record_check "codex login status" run_as_tenant "$CODEX_BIN" login status -c "$LOGIN_STORE_CONFIG"

exec_log="${LOG_DIR}/codex_exec_jsonl.log"
print_header "Read-only Exec"
printf "log: %s\n" "$exec_log"
if run_as_tenant "$CODEX_BIN" exec --json --sandbox read-only --skip-git-repo-check --cd "$WORK_DIR" "$PROMPT" >"$exec_log" 2>&1; then
  printf "result: PASS\n"
  passed=$((passed + 1))
else
  printf "result: FAIL\n"
  tail -n 60 "$exec_log"
  failed=$((failed + 1))
fi

thread_id="$(sed -n 's/.*"thread_id":"\([^"]*\)".*/\1/p' "$exec_log" | head -n 1)"
if [ -n "$thread_id" ]; then
  printf "thread_id: %s\n" "$thread_id"
  record_check "resume thread" run_as_tenant "$CODEX_BIN" exec resume --json --skip-git-repo-check "$thread_id" "Continue in one short sentence."
else
  print_header "Resume"
  printf "result: SKIP\n"
  printf "no thread_id found in exec output\n"
  skipped=$((skipped + 1))
fi

print_header "Credential File Permissions"
auth_file="${CODEX_HOME}/auth.json"
if run_as_tenant test -f "$auth_file"; then
  printf "auth file: present\n"
  passed=$((passed + 1))
else
  printf "auth file: missing at %s\n" "$auth_file"
  failed=$((failed + 1))
fi

if [ -n "${OTHER_USER:-}" ]; then
  printf "checking OTHER_USER=%s cannot read tenant auth file\n" "$OTHER_USER"
  if run_as_other "$OTHER_USER" cat "$auth_file" >/dev/null 2>&1; then
    printf "result: FAIL, other user could read auth file\n"
    failed=$((failed + 1))
  else
    printf "result: PASS, other user could not read auth file\n"
    passed=$((passed + 1))
  fi
else
  printf "result: SKIP\n"
  printf "set OTHER_USER=<linux_user> to verify cross-tenant credential isolation\n"
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

