"""Shared OpenAI Codex CLI subprocess service."""

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

from cloud_agents.policies import AgentExecutionPolicy, resolve_policy
from cloud_agents.subprocess import provider_env, runuser_argv


logger = logging.getLogger(__name__)

DEFAULT_CODEX_TIMEOUT = int(os.getenv("CODEX_EXEC_TIMEOUT", "120"))


@dataclass
class CodexResult:
    output: str | None
    failure: Literal[
        "auth_failure",
        "timeout",
        "rate_limited",
        "resume_missing",
        "error",
        "empty",
    ] | None = None
    usage: dict | None = None
    elapsed_ms: int | None = None
    provider_session_id: str | None = None
    events: list[dict] | None = None


_process_registry: dict[str, subprocess.Popen] = {}
_process_registry_mu = threading.Lock()


def _codex_bin() -> str:
    return shutil.which("codex") or os.getenv("CODEX_CLI_PATH", "codex")


def codex_home_for(home_dir: str | None, run_as_user: str | None = None) -> str | None:
    if home_dir:
        return os.path.join(home_dir, ".codex")
    if run_as_user:
        return f"/home/{run_as_user}/.codex"
    return None


def _home_dir_for(run_as_user: str | None, home_dir: str | None = None) -> str | None:
    if home_dir:
        return home_dir
    if run_as_user:
        return f"/home/{run_as_user}"
    return None


def _env_for(
    *,
    run_as_user: str | None = None,
    home_dir: str | None = None,
    codex_home: str | None = None,
    strip_openai_env: bool = True,
) -> dict:
    resolved_home = _home_dir_for(run_as_user, home_dir)
    resolved_codex_home = codex_home or codex_home_for(resolved_home, run_as_user)
    return provider_env(
        home_dir=resolved_home,
        provider_home_var="CODEX_HOME",
        provider_home_dir=resolved_codex_home,
        strip_provider_secrets=strip_openai_env,
    )


def _exec_argv(
    *,
    cwd: str,
    policy: str | AgentExecutionPolicy | None = None,
    output_schema: str | None = None,
    resume_session_id: str | None = None,
    ephemeral: bool = False,
) -> list[str]:
    resolved_policy = resolve_policy(policy)
    if resume_session_id:
        argv = [
            _codex_bin(),
            "exec",
            "resume",
            "-c",
            'cli_auth_credentials_store="file"',
            "--json",
            "--skip-git-repo-check",
        ]
        if output_schema:
            argv.extend(["--output-schema", output_schema])
        if ephemeral:
            argv.append("--ephemeral")
        argv.extend([resume_session_id, "-"])
        return argv

    argv = [
        _codex_bin(),
        "exec",
        "-c",
        'cli_auth_credentials_store="file"',
        "--json",
        "--sandbox",
        resolved_policy.codex_sandbox,
        "--cd",
        cwd,
        "--skip-git-repo-check",
    ]
    if output_schema:
        argv.extend(["--output-schema", output_schema])
    if ephemeral:
        argv.append("--ephemeral")
    argv.append("-")
    return argv


def _classify_failure(text: str) -> str:
    lowered = text.lower()
    if any(fragment in lowered for fragment in ("not logged in", "login", "authentication", "auth")):
        return "auth_failure"
    if any(fragment in lowered for fragment in ("rate limit", "usage limit", "quota", "too many requests")):
        return "rate_limited"
    if any(fragment in lowered for fragment in ("thread", "session", "not found", "missing")):
        return "resume_missing"
    return "error"


def parse_jsonl_events(stdout: str, stderr: str = "") -> CodexResult:
    events: list[dict] = []
    output_parts: list[str] = []
    provider_session_id = None
    usage = None
    failure = None

    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("[codex] non-JSON line in --json stream: %r", raw[:160])
            continue

        events.append(obj)
        event_type = obj.get("type")
        if event_type == "thread.started":
            provider_session_id = obj.get("thread_id") or provider_session_id
        elif event_type == "turn.completed":
            if isinstance(obj.get("usage"), dict):
                usage = obj["usage"]
        elif event_type in {"turn.failed", "error"}:
            failure = _classify_failure(json.dumps(obj))

        item = obj.get("item")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "agent_message":
            text = item.get("text") or item.get("message") or ""
            if text:
                output_parts.append(text)

    output = "".join(output_parts).strip()
    if failure:
        return CodexResult(
            output=output or None,
            failure=failure,
            usage=usage,
            provider_session_id=provider_session_id,
            events=events,
        )
    if not events:
        return CodexResult(
            output=None,
            failure=_classify_failure(stderr) if stderr else "empty",
            events=events,
        )
    if not output:
        return CodexResult(
            output=None,
            failure="empty",
            usage=usage,
            provider_session_id=provider_session_id,
            events=events,
        )
    return CodexResult(
        output=output,
        failure=None,
        usage=usage,
        provider_session_id=provider_session_id,
        events=events,
    )


def run_blocking(
    prompt: str,
    cwd: str,
    timeout: int = DEFAULT_CODEX_TIMEOUT,
    run_as_user: str | None = None,
    policy: str | AgentExecutionPolicy | None = None,
    output_schema: str | None = None,
    home_dir: str | None = None,
    ephemeral: bool = False,
) -> CodexResult:
    started_at = time.monotonic()
    argv = _exec_argv(
        cwd=cwd,
        policy=policy,
        output_schema=output_schema,
        ephemeral=ephemeral,
    )
    cmd = runuser_argv(run_as_user, argv)
    env = _env_for(run_as_user=run_as_user, home_dir=home_dir)
    logger.info("[codex] run_blocking: cwd=%s timeout=%ds run_as_user=%s", cwd, timeout, run_as_user)

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
    except subprocess.TimeoutExpired:
        logger.warning("[codex] run_blocking timed out after %ss", timeout)
        return CodexResult(output=None, failure="timeout")
    except Exception as exc:
        logger.warning("[codex] run_blocking failed: %s", exc)
        return CodexResult(output=None, failure="error")

    parsed = parse_jsonl_events(result.stdout or "", result.stderr or "")
    parsed.elapsed_ms = int((time.monotonic() - started_at) * 1000)
    if result.returncode != 0 and not parsed.failure:
        parsed.failure = _classify_failure((result.stderr or "") + "\n" + (result.stdout or ""))
    return parsed


def resume_blocking(
    provider_session_id: str,
    prompt: str,
    cwd: str,
    timeout: int = DEFAULT_CODEX_TIMEOUT,
    run_as_user: str | None = None,
    policy: str | AgentExecutionPolicy | None = None,
    output_schema: str | None = None,
    home_dir: str | None = None,
) -> CodexResult:
    started_at = time.monotonic()
    argv = _exec_argv(
        cwd=cwd,
        policy=policy,
        output_schema=output_schema,
        resume_session_id=provider_session_id,
    )
    cmd = runuser_argv(run_as_user, argv)
    env = _env_for(run_as_user=run_as_user, home_dir=home_dir)
    logger.info(
        "[codex] resume_blocking: provider_session=%s cwd=%s timeout=%ds run_as_user=%s",
        provider_session_id,
        cwd,
        timeout,
        run_as_user,
    )

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
    except subprocess.TimeoutExpired:
        logger.warning("[codex] resume_blocking timed out after %ss", timeout)
        return CodexResult(output=None, failure="timeout")
    except Exception as exc:
        logger.warning("[codex] resume_blocking failed: %s", exc)
        return CodexResult(output=None, failure="error")

    parsed = parse_jsonl_events(result.stdout or "", result.stderr or "")
    parsed.elapsed_ms = int((time.monotonic() - started_at) * 1000)
    if result.returncode != 0 and not parsed.failure:
        parsed.failure = _classify_failure((result.stderr or "") + "\n" + (result.stdout or ""))
    return parsed


def stream_exec(
    prompt: str,
    cwd: str,
    timeout: int | None = None,
    run_as_user: str | None = None,
    policy: str | AgentExecutionPolicy | None = None,
    provider_session_id: str | None = None,
    home_dir: str | None = None,
) -> Generator[tuple[str, str], None, CodexResult]:
    argv = _exec_argv(
        cwd=cwd,
        policy=policy,
        resume_session_id=provider_session_id,
    )
    cmd = runuser_argv(run_as_user, argv)
    env = _env_for(run_as_user=run_as_user, home_dir=home_dir)
    turn_timeout = timeout or DEFAULT_CODEX_TIMEOUT
    stdout = []
    stderr = []

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        text=True,
        env=env,
    )
    registry_key = provider_session_id or str(proc.pid)
    with _process_registry_mu:
        _process_registry[registry_key] = proc

    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        started_at = time.monotonic()

        while True:
            if time.monotonic() - started_at > turn_timeout:
                proc.kill()
                yield ("error", f"Codex timed out after {turn_timeout}s.")
                return CodexResult(output=None, failure="timeout")

            ready, _, _ = select.select([proc.stdout, proc.stderr], [], [], 1.0)
            if not ready and proc.poll() is not None:
                break

            for stream in ready:
                raw = stream.readline()
                if raw == "":
                    continue
                if stream is proc.stderr:
                    stderr.append(raw)
                    continue
                stdout.append(raw)
                for event in _event_pairs_from_json_line(raw):
                    yield event

        remaining_stdout = proc.stdout.read() if proc.stdout else ""
        if remaining_stdout:
            stdout.append(remaining_stdout)
            for line in remaining_stdout.splitlines():
                for event in _event_pairs_from_json_line(line):
                    yield event
        remaining_stderr = proc.stderr.read() if proc.stderr else ""
        if remaining_stderr:
            stderr.append(remaining_stderr)

        result = parse_jsonl_events("".join(stdout), "".join(stderr))
        if proc.returncode not in (0, None) and not result.failure:
            result.failure = _classify_failure("".join(stderr) + "\n" + "".join(stdout))
        if result.failure:
            yield ("error", result.failure)
        return result
    finally:
        with _process_registry_mu:
            _process_registry.pop(registry_key, None)
        if proc.poll() is None:
            proc.kill()


def _event_pairs_from_json_line(raw: str) -> list[tuple[str, str]]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []
    event_type = obj.get("type")
    if event_type == "thread.started" and obj.get("thread_id"):
        return [("provider_session", obj["thread_id"])]
    if event_type == "turn.completed" and isinstance(obj.get("usage"), dict):
        return [("context_status", json.dumps(obj["usage"]))]
    if event_type in {"turn.failed", "error"}:
        return [("error", _classify_failure(json.dumps(obj)))]

    item = obj.get("item")
    if not isinstance(item, dict):
        return []
    if item.get("type") == "agent_message":
        text = item.get("text") or item.get("message") or ""
        return [("delta", text)] if text else []
    if item.get("type") in {"command_execution", "file_change", "tool_call"}:
        label = item.get("command") or item.get("path") or item.get("name") or item.get("type")
        return [("activity", str(label))]
    return []


def terminate_session(local_process_id_or_session_id: str) -> None:
    with _process_registry_mu:
        proc = _process_registry.pop(local_process_id_or_session_id, None)
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def login_status(run_as_user: str | None = None, home_dir: str | None = None) -> CodexResult:
    cmd = runuser_argv(
        run_as_user,
        [_codex_bin(), "login", "status", "-c", 'cli_auth_credentials_store="file"'],
    )
    try:
        result = subprocess.run(
            cmd,
            cwd=_home_dir_for(run_as_user, home_dir) or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30,
            env=_env_for(run_as_user=run_as_user, home_dir=home_dir),
        )
    except subprocess.TimeoutExpired:
        return CodexResult(output=None, failure="timeout")
    except Exception as exc:
        logger.warning("[codex] login_status failed: %s", exc)
        return CodexResult(output=None, failure="error")

    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        return CodexResult(output=output or None, failure=_classify_failure(output))
    return CodexResult(output=output or None, failure=None if output else "empty")


def logout(run_as_user: str | None = None, home_dir: str | None = None) -> CodexResult:
    cmd = runuser_argv(
        run_as_user,
        [_codex_bin(), "logout", "-c", 'cli_auth_credentials_store="file"'],
    )
    try:
        result = subprocess.run(
            cmd,
            cwd=_home_dir_for(run_as_user, home_dir) or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30,
            env=_env_for(run_as_user=run_as_user, home_dir=home_dir),
        )
    except subprocess.TimeoutExpired:
        return CodexResult(output=None, failure="timeout")
    except Exception as exc:
        logger.warning("[codex] logout failed: %s", exc)
        return CodexResult(output=None, failure="error")
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        return CodexResult(output=output or None, failure=_classify_failure(output))
    return CodexResult(output=output or "", failure=None)
