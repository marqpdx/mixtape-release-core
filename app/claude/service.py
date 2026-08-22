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
import threading
from collections.abc import Generator

logger = logging.getLogger(__name__)

# Set CLAUDE_PTY_DEBUG=1 to log every raw PTY line to DEBUG.  Useful when
# the chrome-suppression logic is misbehaving and you need real samples.
_PTY_DEBUG = os.getenv("CLAUDE_PTY_DEBUG") == "1"

# ---------------------------------------------------------------------------
# PTY constants
# ---------------------------------------------------------------------------

# Comprehensive ANSI stripper: handles standard CSI, private-param CSI (><=?),
# OSC, character-set designations, and bare Fe sequences.
_ANSI_RE = re.compile(
    r"\x1b(?:"
    # OSC must come BEFORE Fe: ']' (U+005D, code 93) falls inside the Fe range
    # [@-Z\\-_] (codes 64–95), so 'Fe first' would strip only \x1b] and leave
    # the OSC payload (e.g. "8;id=...;URL8;;") as plain text in the buffer.
    r"\][^\x07\x1b]*(?:\x07|\x1b\\)"    # OSC sequences (hyperlinks, titles, etc.)
    r"|[@-Z\\-_]"                         # Fe sequences (ESC + single byte)
    r"|\[[0-9;:<=>?]*[ -/]*[@-~]"        # CSI — standard + private params (>, ?, etc.)
    r"|[()]."                             # Character set designations (ESC ( B …)
    r")"
)
_TOOL_PREFIX = "⯎ "  # ⎿
_PROMPT_RE = re.compile(r"^[>❯]\s*$")
_CONTEXT_RE = re.compile(r"([\d,]+)\s*/\s*([\d,]+)\s*tokens?\s*used\s*\(([\d.]+)%\)")
_COMPACT_DONE_RE = re.compile(r"compacted|summarized|compressed", re.IGNORECASE)

# TUI chrome lines to suppress from the delta stream.
# Claude Code renders separator lines and status bars around each exchange;
# these are visual scaffolding, not Claude's response text.
_UI_CHROME_RE = re.compile(
    r"^(?:"
    r"─{5,}"          # horizontal separator (──────...)
    r"|[╭╰│╮╯]"       # box-drawing corners / sides (welcome screen)
    r"|⏵⏵"            # status bar marker (bypass permissions indicator)
    r"|▐|▛|▝"         # block graphics from Claude Code logo
    r"|◐|◑|◒|◓"       # effort / spinner indicators (◐ medium · /effort)
    r"|▎"              # sidebar / indented-content marker
    r"|/rc\b"          # remote connection status (/rc connecting… /rc connected)
    r")",
    re.UNICODE,
)

# Model name pattern used in the conversation header: "[cwd] | Sonnet 4.6..."
# The header is cursor-positioned so letters may have ANSI codes between them,
# but after stripping, "| Sonnet N" or "| Claude N" is a reliable signal.
_HEADER_RE = re.compile(r"\|\s*(?:Sonnet|Claude|Opus|Haiku)\s*\d", re.IGNORECASE)

# Patterns that indicate Claude Code is showing an interactive setup dialog,
# not a conversation prompt. We must respond to these during spawn.
_API_KEY_PROMPT_RE = re.compile(r"Do you want to use this API key", re.IGNORECASE)
# The Bypass Permissions warning dialog uses terminal cursor-positioning codes
# between words, so "Bypass Permissions mode" is not a contiguous literal string
# in pexpect's raw buffer. The dialog does include an OSC hyperlink whose URL
# appears as literal bytes — match that instead.
_BYPASS_WARN_RE = re.compile(r"code\.claude\.com", re.IGNORECASE)
_SETUP_DIALOG_RE = re.compile(r"Enter to confirm|Esc to cancel", re.IGNORECASE)

# Session UUID → pexpect.spawn handle.
_pty_registry: dict[str, object] = {}
# Per-session lock — prevents two concurrent requests from interleaving in the same PTY.
_pty_locks: dict[str, threading.Lock] = {}
_pty_locks_mu = threading.Lock()  # guards _pty_locks dict itself


def _session_lock(session_id: str) -> threading.Lock:
    with _pty_locks_mu:
        if session_id not in _pty_locks:
            _pty_locks[session_id] = threading.Lock()
        return _pty_locks[session_id]


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
        # --ax-screen-reader produces flatter, less decorative output: fewer
        # box-drawing characters, no logo graphics, simpler status bars.
        # --dangerously-skip-permissions remains for headless tool execution.
        args=["--dangerously-skip-permissions", "--ax-screen-reader"],
        cwd=cwd,
        encoding="utf-8",
        timeout=120,
        codec_errors="replace",
        env=env,
        # Wide terminal: reduces line-wrapping artifacts in the raw PTY stream
        # that appear as spurious short chunks after ANSI stripping.
        dimensions=(60, 240),
    )

    # Drive through all startup overlays (Bypass Permissions, welcome screen, etc.)
    # and wait until the conversation-ready signal (ctrl+g) is detected.
    _resolve_startup_dialogs(proc)

    if opening_context:
        proc.sendline(opening_context)
        _wait_for_silence(proc, silence_window=2, total_timeout=30)

    _pty_registry[session_id] = proc
    return proc


def _wait_for_prompt(proc: object, timeout: int = 30) -> bool:
    """
    Wait until the Claude Code input prompt appears after a response.
    Returns True if the prompt was found, False on timeout.

    Used after sending opening_context — not for startup detection (that
    uses ctrl+g inside _resolve_startup_dialogs instead).
    """
    import pexpect
    try:
        idx = proc.expect(
            [
                re.compile(r"\r?\n[>❯](?! \d) "),   # prompt — not a menu item
                re.compile(r"\A[>❯](?! \d) "),
                pexpect.TIMEOUT,
            ],
            timeout=timeout,
        )
        return idx in (0, 1)
    except Exception:
        return False


def _wait_for_silence(proc: object, silence_window: float = 2.0, total_timeout: int = 30) -> bool:
    """
    Wait until the PTY has been silent for silence_window seconds.
    Used after sending opening_context to know Claude has finished processing.
    Returns True if silence was detected within total_timeout, False otherwise.
    """
    import pexpect, time
    deadline = time.time() + total_timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            idx = proc.expect(
                [re.compile(r"[\s\S]", re.DOTALL), pexpect.TIMEOUT],
                timeout=min(silence_window, remaining),
            )
        except Exception:
            return False
        if idx == 1:
            return True  # silence_window seconds of no output
    return False


def _resolve_startup_dialogs(proc: object, max_rounds: int = 15) -> bool:
    """
    Drive through all startup overlays Claude Code shows before the conversation
    interface is ready.

    Claude Code is a full TUI app — dialog text uses terminal cursor-positioning
    codes between words, so plain text patterns fail. We detect dialogs via:

      • _BYPASS_WARN_RE  — matches the literal URL in the OSC hyperlink that the
                           Bypass Permissions dialog embeds; URL text is never
                           cursor-positioned, so it appears as a contiguous literal
                           string in pexpect's raw buffer.
      • "❯"              — after the Bypass Permissions dialog is dismissed, the
                           welcome screen shows a suggestion (`❯ Try "fix type…"`).
                           Any ❯ that appears before ctrl+g is a startup overlay
                           menu cursor; pressing Enter dismisses it.
      • "ctrl+g"         — appears in the conversation input-area header once Claude
                           Code is truly ready for a conversation turn. This is the
                           authoritative ready signal.

    Pattern ordering matters: pexpect matches the leftmost hit in the buffer. By
    listing the Bypass Permissions URL before ❯, we handle that dialog first even
    though ❯ also appears inside it. ctrl+g is listed before ❯ so that once the
    conversation interface loads, we detect readiness before any input-area ❯.

    Returns True if ctrl+g was detected (conversation ready), False if we timed out.
    """
    import pexpect

    for _ in range(max_rounds):
        try:
            idx = proc.expect(
                [
                    _BYPASS_WARN_RE,                                                 # 0: Bypass Permissions URL
                    re.compile(r"❯"),                                                # 1: startup suggestion
                    re.compile(r"Do you want to use this API key", re.IGNORECASE),  # 2: API key fallback
                    re.compile(r"Enter to confirm", re.IGNORECASE),                 # 3: generic confirm
                    pexpect.TIMEOUT,                                                 # 4
                ],
                timeout=20,
            )
        except Exception:
            break

        if idx == 0:
            # Bypass Permissions: cursor on '❯ 1. No, exit' — DOWN+ENTER to reach Yes.
            logger.info("[claude] PTY startup: Bypass Permissions dialog — accepting (DOWN+ENTER)")
            proc.send("\x1b[B\r")
        elif idx == 1:
            # Welcome screen suggestion pre-fills the input area with '❯ Try "..."'.
            # Enter would EXECUTE the suggestion; ESC clears it without executing.
            # ctrl+g (idx 1) is rendered with per-character ANSI codes in the raw
            # buffer so it's not a contiguous literal pexpect can match — instead
            # we use ESC + silence as the ready signal.
            logger.info("[claude] PTY startup: startup suggestion (❯) — pressing ESC to clear")
            proc.send("\x1b")
            # Wait for TUI to re-render and settle; silence = input area is ready.
            _wait_for_silence(proc, silence_window=2, total_timeout=15)
            logger.info("[claude] PTY startup: TUI settled after ESC — ready")
            return True
        elif idx == 2:
            logger.info("[claude] PTY startup: API key dialog — declining (CC account)")
            proc.send("\r")
        elif idx == 3:
            logger.info("[claude] PTY startup: confirm dialog — pressing Enter")
            proc.send("\r")
        else:
            logger.info("[claude] PTY startup: timeout without ready signal")
            break

    return False


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

    Timeout strategy:
      - Before Claude starts responding (thinking/file-reading phase): 60s patience.
      - Once response content is flowing: 10s inter-line silence ends the stream.

    Chrome suppression:
      _UI_CHROME_RE strips TUI scaffolding (separators, status bars, logo graphics)
      that Claude Code renders around the conversation but is not part of the response.
      The message echo (first non-empty line right after sendline) is also suppressed.

    End-of-response detection:
      After real content has been seen, a second appearance of the ⏵⏵ status bar
      marker signals that Claude has finished and the TUI has re-rendered. We break
      immediately rather than waiting for the full inter-line silence.

    Concurrency:
      A per-session lock prevents two concurrent requests from interleaving reads
      in the same PTY.  Callers block until the previous exchange finishes.
    """
    import pexpect

    lock = _session_lock(session_id)
    if not lock.acquire(timeout=90):
        logger.warning("[claude] send_to_pty: lock timeout for session=%s", session_id)
        yield ("error", "Session busy — another exchange is still running.")
        return

    try:
        yield from _send_to_pty_locked(session_id, message, cwd)
    finally:
        lock.release()


def _send_to_pty_locked(
    session_id: str,
    message: str,
    cwd: str,
) -> Generator[tuple[str, str], None, None]:
    import pexpect

    proc = get_or_spawn(session_id, cwd)
    proc.sendline(message)

    response_started = False   # True once we yield a non-chrome delta line
    echo_suppressed = False    # True after we've skipped the first message echo line
    status_bar_count = 0       # ⏵⏵ appearances; second after response_started = done

    while True:
        # Long patience before Claude starts; short once content is flowing.
        timeout = 10 if response_started else 60
        try:
            idx = proc.expect([re.compile(r"\r?\n"), pexpect.TIMEOUT, pexpect.EOF], timeout=timeout)
        except pexpect.EOF:
            break
        except Exception:
            break

        chunk_raw = proc.before or ""
        chunk = _strip_ansi(chunk_raw).strip()

        if _PTY_DEBUG:
            logger.debug("[claude] PTY raw=%r stripped=%r", chunk_raw[:120], chunk[:80])

        if idx == 2:  # EOF
            break

        if idx == 1:  # silence timeout
            if chunk:
                for pair in _classify_line(chunk):
                    yield pair
            logger.debug("[claude] send_to_pty: timeout fallback (response_started=%s)", response_started)
            yield ("fallback", "")
            break

        # idx == 0: got a newline
        if not chunk:
            continue

        # Prompt line — response complete.
        if _PROMPT_RE.match(chunk):
            break

        # ⏵⏵ status bar — count occurrences; second one after real content = done.
        if "⏵⏵" in chunk:
            status_bar_count += 1
            if response_started and status_bar_count >= 2:
                logger.debug("[claude] send_to_pty: second ⏵⏵ detected — response complete")
                break
            continue  # suppress status bar from delta stream

        # Other TUI chrome — suppress.
        if _UI_CHROME_RE.match(chunk):
            continue

        # Conversation header line: "[cwd] | Sonnet 4.6 ... ctrl+g to edit in Vim"
        # This line appears before AND after Claude's response as TUI scaffolding.
        if _HEADER_RE.search(chunk):
            continue

        # Suppress the message echo (first non-chrome line mirrors what we sent).
        if not echo_suppressed:
            echo_suppressed = True
            # Check if this line looks like the echo of our message.
            msg_start = message[:40].strip().lower()
            if msg_start and chunk.lower().startswith(msg_start[:20]):
                continue  # skip message echo

        pairs = list(_classify_line(chunk))
        for pair in pairs:
            yield pair
        # Only promote to "response started" on actual prose content, not tool
        # calls or token-count lines.  Activity events mean Claude is still
        # working (reading files, running tools); switching to the short timeout
        # there causes premature fallback on anything taking > 10s per call.
        if any(event_type == "delta" for event_type, _ in pairs):
            response_started = True


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
