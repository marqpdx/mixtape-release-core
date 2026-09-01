"""
claude/service.py — Shared Claude Code subprocess service.

Three variants:
  run_blocking(prompt, cwd, timeout) → str | None
  stream(prompt, cwd)               → Generator[str, None, None]
  get_or_spawn / send_to_session    → stream-json interactive session (Phase 2C)

Constraints (from planning/catalyst/claude-code-ingest-architecture.md):
  - Do NOT pass --model — silently hangs in non-interactive mode.
  - Prompts via stdin only — never as CLI arguments (ARG_MAX risk on large prompts).
  - --dangerously-skip-permissions is correct for server-side automation.
  - stream-json turns must have hard timeouts; stalled subprocesses are dropped.

Interactive session notes (stream-json mode):
  - One persistent subprocess per AtriumSession UUID, keyed in _session_registry.
  - Process runs: claude -p --dangerously-skip-permissions --verbose
      --input-format stream-json --output-format stream-json --include-partial-messages
  - Each turn: write one JSONL user message to stdin, read JSON events from stdout
    until a "result" event signals turn complete.
  - No PTY, no ANSI stripping, no TUI chrome parsing.
  - Safe for local dev (single-process Uvicorn). Not safe for multi-worker production.
"""

from __future__ import annotations

import json
import logging
import os
import select
import shutil
import subprocess
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TURN_TIMEOUT = int(os.getenv("CLAUDE_SESSION_TURN_TIMEOUT", "300"))


@dataclass
class ClaudeResult:
    output: str | None
    failure: Literal["auth_failure", "timeout", "error", "empty"] | None = None
    usage: dict | None = None
    elapsed_ms: int | None = None


def _claude_bin() -> str:
    return shutil.which("claude") or os.getenv("CLAUDE_CODE_PATH", "claude")


def _strip_api_key(env: dict) -> dict:
    """Remove API key vars so Claude Code uses the subscription account."""
    env = env.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY_HELPER", None)
    return env


# ---------------------------------------------------------------------------
# run_blocking / stream — one-shot -p variants (unchanged)
# ---------------------------------------------------------------------------

def run_blocking(
    prompt: str,
    cwd: str,
    timeout: int = 90,
    run_as_user: str | None = None,
    log_context: dict | None = None,
) -> ClaudeResult:
    """
    Run claude -p with a prompt via stdin. Returns a ClaudeResult.
    When run_as_user is set, the subprocess runs via runuser as that Linux user
    with HOME set explicitly so ~/.claude/ credentials resolve correctly.
    Raises nothing — logs warnings on any error.
    """
    bin_path = _claude_bin()
    logger.info("[claude] run_blocking: cwd=%s timeout=%ds run_as_user=%s", cwd, timeout, run_as_user)

    env = _strip_api_key(os.environ.copy())
    if run_as_user:
        cmd = [
            "runuser", "-u", run_as_user, "--", bin_path,
            "-p", "--dangerously-skip-permissions", "--output-format", "json",
        ]
        env["HOME"] = f"/home/{run_as_user}"
    else:
        cmd = [bin_path, "-p", "--dangerously-skip-permissions", "--output-format", "json"]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            if "Not logged in" in stdout or "Please run /login" in stdout:
                logger.warning(
                    "[claude] run_blocking auth failure exit=%s stdout=%r stderr=%r",
                    result.returncode,
                    stdout[:500],
                    stderr[:500],
                )
                return ClaudeResult(output=None, failure="auth_failure")
            logger.warning(
                "[claude] run_blocking non-zero exit %s: stdout=%r stderr=%r",
                result.returncode,
                stdout[:500],
                stderr[:500],
            )
            return ClaudeResult(output=None, failure="error")
        output = result.stdout.strip()
        if not output:
            logger.warning("[claude] run_blocking: empty stdout")
            return ClaudeResult(output=None, failure="empty")
        usage = None
        elapsed_ms = None
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            parsed_output = output
        else:
            if isinstance(payload, dict):
                parsed_output = str(payload.get("result") or "").strip()
                usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
                elapsed_ms = payload.get("duration_ms") or payload.get("duration_api_ms")
            else:
                parsed_output = output
        if usage or elapsed_ms:
            logger.info(
                "[claude] run_blocking usage context=%s input_tokens=%s output_tokens=%s elapsed_ms=%s",
                log_context or {},
                (usage or {}).get("input_tokens"),
                (usage or {}).get("output_tokens"),
                elapsed_ms,
            )
        if not parsed_output:
            logger.warning("[claude] run_blocking: empty parsed result context=%s", log_context or {})
            return ClaudeResult(output=None, failure="empty", usage=usage, elapsed_ms=elapsed_ms)
        return ClaudeResult(output=parsed_output, failure=None, usage=usage, elapsed_ms=elapsed_ms)
    except subprocess.TimeoutExpired:
        logger.warning("[claude] run_blocking: timed out after %ds", timeout)
        return ClaudeResult(output=None, failure="timeout")
    except Exception as exc:
        logger.warning("[claude] run_blocking: %s", exc)
        return ClaudeResult(output=None, failure="error")


def stream(prompt: str, cwd: str) -> Generator[str, None, None]:
    """
    Stream claude -p output line-by-line via Popen stdout pipe.
    Caller is responsible for lifecycle management (no hard timeout here).
    Cleans up the process on error via try/finally.
    """
    bin_path = _claude_bin()
    logger.info("[claude] stream: cwd=%s", cwd)
    proc = subprocess.Popen(
        [bin_path, "-p", "--dangerously-skip-permissions"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        text=True,
        env=_strip_api_key(os.environ.copy()),
    )
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            yield line
        proc.wait()
        if proc.returncode != 0:
            err = proc.stderr.read(200) if proc.stderr else ""
            logger.warning("[claude] stream: non-zero exit %s: %s", proc.returncode, err)
    except Exception:
        proc.kill()
        proc.wait()
        raise
    finally:
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()


# ---------------------------------------------------------------------------
# Interactive session — stream-json subprocess (Phase 2C)
# ---------------------------------------------------------------------------

# Session UUID → subprocess.Popen handle.
_session_registry: dict[str, subprocess.Popen] = {}
# Per-session lock — prevents two concurrent requests interleaving on the same process.
_session_locks: dict[str, threading.RLock] = {}
_session_locks_mu = threading.Lock()


def _session_lock(session_id: str) -> threading.RLock:
    with _session_locks_mu:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.RLock()
        return _session_locks[session_id]


def _is_alive(proc: subprocess.Popen) -> bool:
    return proc.poll() is None


def get_or_spawn(
    session_id: str,
    cwd: str,
    opening_context: str | None = None,
    run_as_user: str | None = None,
) -> subprocess.Popen:
    """
    Return the live stream-json subprocess for session_id, spawning a new one
    if the registry entry is missing or the process has exited.

    opening_context: if provided, sent as the first user message before returning.
    run_as_user: when set, spawns the subprocess via runuser as that Linux user.
    """
    with _session_lock(session_id):
        existing = _session_registry.get(session_id)
        if existing is not None and _is_alive(existing):
            return existing
        if existing is not None:
            _session_registry.pop(session_id, None)

        bin_path = _claude_bin()
        logger.info(
            "[claude] spawning stream-json session: session=%s cwd=%s run_as_user=%s",
            session_id, cwd, run_as_user,
        )

        env = _strip_api_key(os.environ.copy())
        session_args = [
            "-p",
            "--dangerously-skip-permissions",
            "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
        ]
        if run_as_user:
            cmd = ["runuser", "-u", run_as_user, "--", bin_path, *session_args]
            env["HOME"] = f"/home/{run_as_user}"
        else:
            cmd = [bin_path, *session_args]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            text=True,
            env=env,
        )

        _session_registry[session_id] = proc

        if opening_context:
            # Drain the opening context response before returning — caller expects
            # the session to be ready for their first real message.
            _send_message(proc, opening_context)
            for _ in _read_turn(proc, session_id, timeout=DEFAULT_SESSION_TURN_TIMEOUT):
                pass  # discard opening context response

        return proc


def _send_message(proc: subprocess.Popen, text: str) -> None:
    """Write one user message as a JSONL line to the process stdin."""
    msg = json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    })
    proc.stdin.write(msg + "\n")
    proc.stdin.flush()


def _read_turn(
    proc: subprocess.Popen,
    session_id: str,
    timeout: int | None = None,
) -> Generator[tuple[str, str], None, None]:
    """
    Read JSON events from stdout until a "result" event signals turn complete.
    Yields (event_type, payload) pairs for Atrium SSE:
      ("delta",          text)          — response text chunk
      ("activity",       text)          — tool call in progress (file read, bash, etc.)
      ("context_status", json_str)      — token-count update
      ("error",          message)       — is_error result
    Silently drops: system/init, rate_limit_event, stream_event/message_start,
    stream_event/content_block_stop, stream_event/message_delta/stop, assistant,
    user (tool-result routing), thinking blocks.
    """
    import json as _json

    active_tool_name: str | None = None
    started_at = time.monotonic()
    turn_timeout = timeout or DEFAULT_SESSION_TURN_TIMEOUT

    while True:
        remaining = turn_timeout - (time.monotonic() - started_at)
        if remaining <= 0:
            logger.warning(
                "[claude] stream-json turn timeout: session=%s timeout=%ss",
                session_id,
                turn_timeout,
            )
            _session_registry.pop(session_id, None)
            try:
                proc.kill()
            except Exception:
                pass
            yield ("error", f"Claude Code timed out after {turn_timeout}s.")
            return

        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
        if not ready:
            continue

        raw = proc.stdout.readline()
        if raw == "":
            logger.warning(
                "[claude] stream-json ended before result: session=%s returncode=%s",
                session_id,
                proc.poll(),
            )
            _session_registry.pop(session_id, None)
            yield ("error", "Claude Code exited before completing the turn.")
            return

        raw = raw.strip()
        if not raw:
            continue

        try:
            obj = _json.loads(raw)
        except _json.JSONDecodeError:
            logger.debug("[claude] stream-json non-JSON line: %r", raw[:120])
            continue

        t = obj.get("type")

        # ── turn complete ────────────────────────────────────────────────────
        if t == "result":
            if obj.get("is_error"):
                msg = obj.get("error", {}).get("message", "Claude Code returned an error.")
                logger.warning("[claude] stream-json error result: session=%s msg=%s", session_id, msg[:200])
                yield ("error", msg)
            else:
                logger.info(
                    "[claude] stream-json turn complete: session=%s turns=%s duration_ms=%s",
                    session_id,
                    obj.get("num_turns"),
                    obj.get("duration_api_ms"),
                )
                usage = obj.get("usage") or {}
                input_tokens = usage.get("input_tokens") or 0
                if input_tokens:
                    _CONTEXT_LIMIT = 200_000
                    pct = round(input_tokens / _CONTEXT_LIMIT * 100, 1)
                    yield ("context_status", _json.dumps({
                        "used": input_tokens,
                        "total": _CONTEXT_LIMIT,
                        "pct": pct,
                    }))
            return

        # ── stream events ────────────────────────────────────────────────────
        if t == "stream_event":
            event = obj.get("event", {})
            et = event.get("type")

            if et == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "tool_use":
                    active_tool_name = block.get("name", "tool")
                    logger.debug("[claude] tool call started: %s", active_tool_name)
                    yield ("activity", active_tool_name)
                elif block.get("type") == "text":
                    active_tool_name = None

            elif et == "content_block_delta":
                delta = event.get("delta", {})
                dt = delta.get("type")

                if dt == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield ("delta", text)

                elif dt == "input_json_delta":
                    # Tool call argument being assembled — no user-visible text yet.
                    pass

                elif dt == "thinking_delta":
                    # Extended thinking block — internal to Claude, not surfaced.
                    pass

            elif et == "content_block_stop":
                active_tool_name = None

            # message_start, message_delta, message_stop — no user-visible payload.

        # ── system events ────────────────────────────────────────────────────
        elif t == "system":
            sub = obj.get("subtype")
            if sub == "thinking_tokens":
                pass  # extended thinking token count, not surfaced
            elif sub == "status":
                logger.debug("[claude] system status: %s", obj.get("status"))
            elif sub == "init":
                logger.info("[claude] stream-json init: session=%s", obj.get("session_id"))

        # ── assistant / user (tool routing) — skip ──────────────────────────
        elif t in ("assistant", "user", "rate_limit_event"):
            pass

        else:
            logger.debug("[claude] stream-json unknown event type=%s", t)


def is_session_alive(session_id: str) -> bool:
    proc = _session_registry.get(session_id)
    return proc is not None and _is_alive(proc)


def send_to_session(
    session_id: str,
    message: str,
    cwd: str,
    opening_context: str | None = None,
    run_as_user: str | None = None,
    timeout: int | None = None,
) -> Generator[tuple[str, str], None, None]:
    """
    Send message to the session's stream-json subprocess and yield SSE event pairs.
    Acquires a per-session lock so concurrent Django requests serialize cleanly.

    opening_context: injected only on cold spawn (process was dead or missing).
    run_as_user: passed to get_or_spawn on cold spawn; ignored if session already live.
    timeout: max seconds to wait for this turn's stream-json result event.
    """
    lock = _session_lock(session_id)
    if not lock.acquire(timeout=90):
        logger.warning("[claude] send_to_session: lock timeout session=%s", session_id)
        yield ("error", "Session busy — another exchange is still running.")
        return

    try:
        proc = get_or_spawn(session_id, cwd, opening_context, run_as_user=run_as_user)
        _send_message(proc, message)
        yield from _read_turn(proc, session_id, timeout=timeout)
    except BrokenPipeError:
        logger.warning("[claude] send_to_session: broken pipe — process died session=%s", session_id)
        _session_registry.pop(session_id, None)
        yield ("error", "Session process exited unexpectedly.")
    except Exception as exc:
        logger.exception("[claude] send_to_session: unexpected error session=%s", session_id)
        yield ("error", str(exc))
    finally:
        lock.release()


def run_session_blocking(
    session_id: str,
    prompt: str,
    cwd: str,
    opening_context: str | None = None,
    run_as_user: str | None = None,
    timeout: int | None = None,
) -> str | None:
    """
    Run one prompt through the persistent stream-json subprocess and collect text.

    This is for batch workers that need the speed/context benefits of the Atrium
    wrapper but want a simple blocking string result instead of SSE events.
    When run_as_user is set, the subprocess spawns via runuser as that Linux user.
    """
    chunks: list[str] = []
    errors: list[str] = []
    for event_type, text in send_to_session(
        session_id,
        prompt,
        cwd,
        opening_context,
        run_as_user=run_as_user,
        timeout=timeout,
    ):
        if event_type == "delta":
            chunks.append(text)
        elif event_type == "error":
            errors.append(text)

    output = "".join(chunks).strip()
    if output:
        return output
    if errors:
        logger.warning(
            "[claude] run_session_blocking: no output session=%s error=%s",
            session_id,
            errors[-1][:300],
        )
    else:
        logger.warning("[claude] run_session_blocking: no output session=%s", session_id)
    return None


def terminate_session(session_id: str) -> None:
    """Terminate the stream-json subprocess for session_id."""
    proc = _session_registry.pop(session_id, None)
    if proc is None:
        return
    try:
        if _is_alive(proc):
            proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backwards-compat shims — callers still using PTY names
# ---------------------------------------------------------------------------

def get_or_spawn_pty(session_id: str, cwd: str, opening_context: str | None = None):
    """Deprecated name — delegates to get_or_spawn."""
    return get_or_spawn(session_id, cwd, opening_context)


def send_to_pty(
    session_id: str,
    message: str,
    cwd: str,
    opening_context: str | None = None,
) -> Generator[tuple[str, str], None, None]:
    """Deprecated name — delegates to send_to_session."""
    yield from send_to_session(session_id, message, cwd, opening_context)


def is_pty_alive(session_id: str) -> bool:
    """Deprecated name — delegates to is_session_alive."""
    return is_session_alive(session_id)


def terminate_pty(session_id: str) -> None:
    """Deprecated name — delegates to terminate_session."""
    terminate_session(session_id)


def compact_pty(session_id: str, cwd: str) -> str | None:
    """
    Send /compact to the session and collect the summary text.
    Returns the response text or None on failure.
    """
    lock = _session_lock(session_id)
    if not lock.acquire(timeout=30):
        return None
    try:
        proc = get_or_spawn(session_id, cwd)
        _send_message(proc, "/compact")
        parts = []
        for event_type, payload in _read_turn(proc, session_id):
            if event_type == "delta":
                parts.append(payload)
        return "".join(parts).strip() or None
    except Exception:
        return None
    finally:
        lock.release()
