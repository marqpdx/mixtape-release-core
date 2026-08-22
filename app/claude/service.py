"""
claude/service.py — Shared Claude Code subprocess service.

Three variants:
  run_blocking(prompt, cwd, timeout) → str | None
  stream(prompt, cwd)               → Generator[str, None, None]
  get_or_spawn / send_to_pty        → PTY interactive session (Phase 2C)

Constraints (from planning/catalyst/claude-code-ingest-architecture.md):
  - Do NOT pass --model — silently hangs in non-interactive mode.
  - Prompts via stdin only — never as CLI arguments (ARG_MAX risk on large prompts).
  - --dangerously-skip-permissions is correct for server-side automation.
  - No hard timeout on the streaming variant — caller manages lifecycle.

PTY notes:
  - _pty_registry is a module-level dict keyed by AtriumSession UUID string.
  - Safe for local dev (single-process Uvicorn). Not safe for multi-worker production.
  - pty_pid on AtriumSession is for orphan-cleanup management commands only;
    the live handle lives in _pty_registry.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PTY constants
# ---------------------------------------------------------------------------

# Comprehensive ANSI stripper: handles standard CSI, private-param CSI (><=?),
# OSC, character-set designations, and bare Fe sequences.
_ANSI_RE = re.compile(
    r"\x1b(?:"
    r"[@-Z\\-_]"                         # Fe sequences (ESC + single char)
    r"|\[[0-9;:<=>?]*[ -/]*[@-~]"        # CSI — standard + private params (>, ?, etc.)
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC sequences
    r"|[()]."                             # Character set designations (ESC ( B …)
    r")"
)
_TOOL_PREFIX = "⯎ "  # ⎿
_PROMPT_RE = re.compile(r"^[>❯]\s*$")
_CONTEXT_RE = re.compile(r"([\d,]+)\s*/\s*([\d,]+)\s*tokens?\s*used\s*\(([\d.]+)%\)")
_COMPACT_DONE_RE = re.compile(r"compacted|summarized|compressed", re.IGNORECASE)

# Patterns that indicate Claude Code is showing an interactive setup dialog,
# not a conversation prompt. We must respond to these during spawn.
_API_KEY_PROMPT_RE = re.compile(r"Do you want to use this API key", re.IGNORECASE)
_SETUP_DIALOG_RE = re.compile(r"Enter to confirm|Esc to cancel", re.IGNORECASE)

# Session UUID → pexpect.spawn handle.
_pty_registry: dict[str, object] = {}


def _claude_bin() -> str:
    return shutil.which("claude") or os.getenv("CLAUDE_CODE_PATH", "claude")


def run_blocking(prompt: str, cwd: str, timeout: int = 90) -> str | None:
    """
    Run claude -p with a prompt via stdin. Returns stdout stripped, or None on failure.
    Raises nothing — logs warnings and returns None on any error.
    """
    bin_path = _claude_bin()
    logger.info("[claude] run_blocking: cwd=%s timeout=%ds", cwd, timeout)
    try:
        result = subprocess.run(
            [bin_path, "-p", "--dangerously-skip-permissions"],
            input=prompt,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning("[claude] run_blocking non-zero exit %s: %s", result.returncode, result.stderr[:200])
            return None
        output = result.stdout.strip()
        if not output:
            logger.warning("[claude] run_blocking: empty stdout")
            return None
        return output
    except subprocess.TimeoutExpired:
        logger.warning("[claude] run_blocking: timed out after %ds", timeout)
        return None
    except Exception as exc:
        logger.warning("[claude] run_blocking: %s", exc)
        return None


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
# PTY interactive session (Phase 2C)
# ---------------------------------------------------------------------------

def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _classify_line(line: str) -> list[tuple[str, str]]:
    """Return list of (event_type, text) pairs from one cleaned output line."""
    import json

    if not line:
        return []

    m = _CONTEXT_RE.search(line)
    if m:
        used = int(m.group(1).replace(",", ""))
        total = int(m.group(2).replace(",", ""))
        pct = float(m.group(3))
        return [("context_status", json.dumps({"used": used, "total": total, "pct": pct}))]

    if line.startswith(_TOOL_PREFIX):
        return [("activity", line[len(_TOOL_PREFIX):].strip())]

    return [("delta", line + "\n")]


def get_or_spawn(session_id: str, cwd: str, opening_context: str | None = None) -> object:
    """
    Return the live pexpect.spawn for session_id, spawning a new one if
    the registry entry is missing or the process has died.

    opening_context is sent to the new process before returning, allowing
    compact summaries from prior sessions to be injected as context.
    """
    import pexpect

    existing = _pty_registry.get(session_id)
    if existing is not None:
        try:
            if existing.isalive():
                return existing
        except Exception:
            pass
        del _pty_registry[session_id]

    bin_path = _claude_bin()
    logger.info("[claude] spawning PTY: session=%s cwd=%s", session_id, cwd)

    # Strip API key from env so Claude Code uses its subscription account, not the
    # API key that Django has set. Without this, Claude Code shows an interactive
    # "Do you want to use this API key?" dialog that blocks the PTY spawn.
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY_HELPER", None)

    proc = pexpect.spawn(
        bin_path,
        args=["--dangerously-skip-permissions"],
        cwd=cwd,
        encoding="utf-8",
        timeout=120,
        codec_errors="replace",
        env=env,
    )

    # Drive through any remaining setup dialogs (first-run, TOS, etc.).
    _resolve_startup_dialogs(proc)
    # Always drain to the conversation prompt before returning.
    _wait_for_prompt(proc, timeout=30)

    if opening_context:
        proc.sendline(opening_context)
        _wait_for_prompt(proc, timeout=30)

    _pty_registry[session_id] = proc
    return proc


def _wait_for_prompt(proc: object, timeout: int = 30) -> bool:
    """
    Wait until the Claude Code input prompt appears.
    Returns True if the prompt was found, False on timeout.
    """
    import pexpect
    try:
        idx = proc.expect(
            [
                re.compile(r"\r?\n[>❯]\s"),   # prompt on its own line
                re.compile(r"\A[>❯]\s"),       # prompt at buffer start
                pexpect.TIMEOUT,
            ],
            timeout=timeout,
        )
        return idx in (0, 1)
    except Exception:
        return False


def _resolve_startup_dialogs(proc: object, max_rounds: int = 5) -> None:
    """
    After spawn, consume any interactive dialogs Claude Code shows before the
    main conversation prompt (first-run setup, TOS, etc.).

    We do NOT look for ❯ as a "prompt found" signal here — the API key selection
    menu and other menus also contain ❯ and would cause false exits. Instead we
    loop until timeout (no more dialog text detected), then let _wait_for_prompt
    drain to the actual conversation prompt.

    The API key dialog is avoided entirely by stripping ANTHROPIC_API_KEY from
    the PTY env before spawn — this function handles any remaining dialogs.
    """
    import pexpect

    for _ in range(max_rounds):
        try:
            idx = proc.expect(
                [
                    re.compile(r"Do you want to use this API key", re.IGNORECASE),
                    re.compile(r"Enter to confirm", re.IGNORECASE),
                    pexpect.TIMEOUT,
                ],
                timeout=8,
            )
        except Exception:
            break

        if idx == 0:
            logger.info("[claude] PTY startup: API key dialog detected — declining (using CC account)")
            proc.send("\r")
        elif idx == 1:
            logger.info("[claude] PTY startup: confirm dialog detected — pressing Enter")
            proc.send("\r")
        else:
            # Timeout — no more dialogs.
            logger.info("[claude] PTY startup: no dialog within timeout, proceeding to prompt wait")
            break


def is_pty_alive(session_id: str) -> bool:
    proc = _pty_registry.get(session_id)
    if proc is None:
        return False
    try:
        return proc.isalive()
    except Exception:
        return False


def send_to_pty(
    session_id: str,
    message: str,
    cwd: str,
) -> Generator[tuple[str, str], None, None]:
    """
    Write message to the session's PTY and yield (event_type, text) pairs
    until Claude Code returns to its prompt.

    event_type values:
      "delta"          — response text (one line, includes trailing \\n)
      "activity"       — tool-call activity (e.g. "Reading foo.md")
      "context_status" — JSON string with {used, total, pct}
    """
    import pexpect

    proc = get_or_spawn(session_id, cwd)
    proc.sendline(message)

    while True:
        try:
            idx = proc.expect([re.compile(r"\r?\n"), pexpect.TIMEOUT, pexpect.EOF], timeout=3)
        except pexpect.EOF:
            break
        except Exception:
            break

        chunk_raw = proc.before or ""
        chunk = _strip_ansi(chunk_raw).strip()

        if idx == 2:  # EOF
            break

        if idx == 1:  # timeout — prompt not detected; treating silence as end of response
            if chunk:
                for pair in _classify_line(chunk):
                    yield pair
            logger.debug("[claude] send_to_pty: timeout fallback used (prompt not detected)")
            yield ("fallback", "")  # signals the frontend that timeout-based completion fired
            break

        # idx == 0: got a newline
        if not chunk:
            continue

        # Prompt line — response complete.
        if _PROMPT_RE.match(chunk):
            break

        for pair in _classify_line(chunk):
            yield pair


def compact_pty(session_id: str, cwd: str) -> str | None:
    """
    Send /compact to the PTY and wait for Claude Code to finish.
    Returns the compact summary text if captured, else None.
    """
    import pexpect

    proc = get_or_spawn(session_id, cwd)
    proc.sendline("/compact")

    summary_lines: list[str] = []
    while True:
        try:
            idx = proc.expect([re.compile(r"\r?\n"), pexpect.TIMEOUT, pexpect.EOF], timeout=60)
        except pexpect.EOF:
            break
        except Exception:
            break

        chunk = _strip_ansi(proc.before or "").strip()
        if idx in (1, 2):
            break
        if chunk and _PROMPT_RE.match(chunk):
            break
        if chunk:
            summary_lines.append(chunk)

    text = "\n".join(summary_lines).strip()
    return text or None


def terminate_pty(session_id: str) -> str | None:
    """
    Terminate the PTY for session_id.
    Returns whatever compact summary is available in the buffer, if any.
    """
    import pexpect

    proc = _pty_registry.pop(session_id, None)
    if proc is None:
        return None
    try:
        if proc.isalive():
            proc.terminate(force=True)
    except Exception:
        pass
    return None
