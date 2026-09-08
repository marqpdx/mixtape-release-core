#!/usr/bin/env bash
set -u

CODEX_BIN="${CODEX_BIN:-codex}"
CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}"
WORK_DIR="${WORK_DIR:-$(pwd)}"
PROMPT="${PROMPT:-Reply exactly: OK}"
LOG_DIR="${LOG_DIR:-$(mktemp -d -t mixtape-codex-current-user)}"
LOGIN_STORE_CONFIG='cli_auth_credentials_store="file"'

passed=0
failed=0
skipped=0

print_header() {
  printf "\n== %s ==\n" "$1"
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

print_header "Codex Current User Probe"
printf "user: %s\n" "$(id -un)"
printf "home: %s\n" "$HOME"
printf "codex home: %s\n" "$CODEX_HOME"
printf "work dir: %s\n" "$WORK_DIR"
printf "logs: %s\n" "$LOG_DIR"

record_check "codex binary visible" "$CODEX_BIN" --version
record_check "codex login status" env CODEX_HOME="$CODEX_HOME" "$CODEX_BIN" login status -c "$LOGIN_STORE_CONFIG"

if [ "${START_LOGIN:-0}" = "1" ]; then
  print_header "Device Login"
  printf "Starting interactive device login. Follow the printed URL/code in your terminal.\n"
  env CODEX_HOME="$CODEX_HOME" "$CODEX_BIN" login --device-auth -c "$LOGIN_STORE_CONFIG"
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
  printf "set START_LOGIN=1 if this machine needs first-time ChatGPT auth\n"
  skipped=$((skipped + 1))
fi

if [ "${RUN_LIVE_CODEX_EXEC:-0}" = "1" ]; then
  exec_log="${LOG_DIR}/codex_exec_jsonl.log"
  print_header "Read-only Exec"
  printf "log: %s\n" "$exec_log"
  if env CODEX_HOME="$CODEX_HOME" "$CODEX_BIN" exec --json --sandbox read-only --skip-git-repo-check --cd "$WORK_DIR" "$PROMPT" >"$exec_log" 2>&1; then
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
    record_check "resume thread" env CODEX_HOME="$CODEX_HOME" "$CODEX_BIN" exec resume --json --skip-git-repo-check "$thread_id" "Continue in one short sentence."
  else
    print_header "Resume"
    printf "result: SKIP\n"
    printf "no thread_id found in exec output\n"
    skipped=$((skipped + 1))
  fi
else
  print_header "Read-only Exec"
  printf "result: SKIP\n"
  printf "set RUN_LIVE_CODEX_EXEC=1 to call Codex exec/resume from this user\n"
  skipped=$((skipped + 1))
fi

print_header "Credential File"
auth_file="${CODEX_HOME}/auth.json"
if [ -f "$auth_file" ]; then
  printf "auth file: present at %s\n" "$auth_file"
  passed=$((passed + 1))
else
  printf "auth file: missing at %s\n" "$auth_file"
  printf "result: SKIP\n"
  skipped=$((skipped + 1))
fi

print_header "Isolation"
printf "result: SKIP\n"
printf "current-user mode cannot verify Linux tenant user isolation or cross-user auth denial\n"
skipped=$((skipped + 1))

print_header "Summary"
printf "passed: %s\n" "$passed"
printf "failed: %s\n" "$failed"
printf "skipped: %s\n" "$skipped"
printf "logs: %s\n" "$LOG_DIR"

if [ "$failed" -gt 0 ]; then
  exit 1
fi
