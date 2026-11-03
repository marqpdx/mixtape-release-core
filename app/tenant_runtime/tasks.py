# tenant_runtime/tasks.py
"""
Celery tasks for the tenant_runtime app.

run_tenant_claude_login: launches claude auth login as the tenant's Linux user,
captures the URL from its output, passes in the code the person pastes, and
waits for exit.
"""

import logging
import queue
import re
import subprocess
import threading
import time

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

_LOGIN_SUBPROCESS_TIMEOUT = 610  # slightly over the 10-minute session TTL
_URL_RE = re.compile(r"https://\S+")
_DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,}(?:-[A-Z0-9]{4,})+\b")
_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOGIN_POLL_SECONDS = 2


@shared_task(bind=True, name="tenant_runtime.run_tenant_claude_login")
def run_tenant_claude_login(self, runtime_id: str):
    """
    Launch `claude auth login` as the tenant's Linux user and see it through.

    Flow (CLI 2.1.x, ST-3):
      1. Create TenantClaudeLoginSession (status: starting).
      2. Spawn the subprocess as the runtime's Linux user (sudo; the runtime worker only).
      3. Find the login URL anywhere in its output (it arrives wrapped in a terminal
         hyperlink); save it and set status: awaiting_auth.
      4. The person approves in the browser and Anthropic shows them a code. They paste
         it in Settings; it waits in session.pending_code. Type it into the CLI's stdin
         and clear it at once. The code is never logged.
      5. On exit 0: run pre-flight verification; set runtime status: ready.
      6. On non-zero exit, or at the session's expiry whatever the CLI is doing:
         set session/runtime to failed/expired and end the CLI.
    """
    from claude.service import login_argv, run_blocking
    from tenant_runtime.models import TenantClaudeLoginSession, TenantClaudeRuntime

    try:
        runtime = TenantClaudeRuntime.objects.get(id=runtime_id)
    except TenantClaudeRuntime.DoesNotExist:
        logger.error("[tenant_runtime] run_tenant_claude_login: runtime %s not found", runtime_id)
        return

    if not runtime.linux_user:
        logger.error("[tenant_runtime] run_tenant_claude_login: runtime %s has no linux_user", runtime_id)
        return

    session = TenantClaudeLoginSession.objects.create(runtime=runtime)
    logger.info(
        "[tenant_runtime] login session %s starting for runtime %s (user=%s)",
        session.id, runtime_id, runtime.linux_user,
    )

    def fail(status, error, runtime_status, runtime_error):
        session.status = status
        session.error = error
        session.save(update_fields=["status", "error"])
        runtime.status = runtime_status
        runtime.last_verification_error = runtime_error[:500]
        runtime.save(update_fields=["status", "last_verification_error", "updated_at"])

    proc = None
    try:
        proc = subprocess.Popen(
            login_argv(runtime.linux_user),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={"HOME": runtime.home_dir, "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        # A thread reads the output, so a silent CLI can't stop the deadline below.
        lines = queue.Queue()
        threading.Thread(target=_read_lines, args=(proc.stdout, lines), daemon=True).start()

        url_found = False
        code_sent = False
        output_ended = False
        stdout_lines = []

        while proc.poll() is None and not session.is_expired:
            while True:
                try:
                    line = lines.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    output_ended = True
                    break
                line = _plain(line.rstrip())
                stdout_lines = (stdout_lines + [line])[-200:]
                if not url_found:
                    match = _URL_RE.search(line)
                    if match:
                        session.login_url = match.group(0)
                        session.status = TenantClaudeLoginSession.STATUS_AWAITING_AUTH
                        session.save(update_fields=["login_url", "status"])
                        logger.info("[tenant_runtime] login URL detected session=%s", session.id)
                        url_found = True

            if url_found and not code_sent:
                code = (
                    TenantClaudeLoginSession.objects.filter(pk=session.pk)
                    .values_list("pending_code", flat=True).first()
                )
                if code:
                    TenantClaudeLoginSession.objects.filter(pk=session.pk).update(pending_code="")
                    try:
                        proc.stdin.write(code + "\n")
                        proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass  # the CLI has gone; its exit code says why
                    code_sent = True
                    logger.info("[tenant_runtime] sign-in code passed to the CLI session=%s", session.id)

            time.sleep(_LOGIN_POLL_SECONDS)

        if proc.poll() is None:
            # Expired while the CLI waited (for the code, or for nothing).
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.warning("[tenant_runtime] login session %s expired while waiting", session.id)
            fail(
                TenantClaudeLoginSession.STATUS_EXPIRED,
                "Login TTL expired before authentication completed.",
                TenantClaudeRuntime.STATUS_FAILED,
                "Sign-in timed out. Try again.",
            )
            return

        # Collect whatever the CLI printed last.
        while not output_ended:
            try:
                line = lines.get(timeout=2)
            except queue.Empty:
                break
            if line is None:
                output_ended = True
                break
            stdout_lines = (stdout_lines + [_plain(line.rstrip())])[-200:]

        if proc.returncode != 0:
            error_snippet = "\n".join(stdout_lines[-20:])[:1000]
            logger.warning(
                "[tenant_runtime] claude auth login exited %s session=%s output=%r",
                proc.returncode, session.id, error_snippet,
            )
            fail(
                TenantClaudeLoginSession.STATUS_FAILED,
                f"Exit code {proc.returncode}. Output: {error_snippet}",
                TenantClaudeRuntime.STATUS_FAILED,
                f"Exit code {proc.returncode}. Output: {error_snippet}",
            )
            return

        # Exit 0 — run pre-flight verification
        logger.info("[tenant_runtime] auth login exited 0, running pre-flight session=%s", session.id)
        result = run_blocking(
            "say ok", run_as_user=runtime.linux_user, home_dir=runtime.home_dir, timeout=30, tools="",
        )

        if result.failure == "auth_failure":
            error = "Pre-flight verification failed: auth_failure after login completed."
            fail(TenantClaudeLoginSession.STATUS_FAILED, error, TenantClaudeRuntime.STATUS_LOGIN_REQUIRED, error)
            return

        if result.failure:
            error = f"Pre-flight verification failed: {result.failure}."
            fail(TenantClaudeLoginSession.STATUS_FAILED, error, TenantClaudeRuntime.STATUS_FAILED, error)
            return

        # Verification passed
        now = timezone.now()
        session.status = TenantClaudeLoginSession.STATUS_COMPLETE
        session.completed_at = now
        session.save(update_fields=["status", "completed_at"])

        runtime.status = TenantClaudeRuntime.STATUS_READY
        runtime.last_verified_at = now
        runtime.last_verification_error = ""
        runtime.save(update_fields=["status", "last_verified_at", "last_verification_error", "updated_at"])
        logger.info("[tenant_runtime] runtime %s is ready", runtime_id)

    except Exception as exc:
        logger.exception("[tenant_runtime] run_tenant_claude_login unexpected error session=%s", session.id)
        fail(TenantClaudeLoginSession.STATUS_FAILED, str(exc)[:500], TenantClaudeRuntime.STATUS_FAILED, str(exc))
    finally:
        # The code never outlives the attempt, whatever happened.
        TenantClaudeLoginSession.objects.filter(pk=session.pk).exclude(pending_code="").update(pending_code="")
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()


def _read_lines(stream, lines):
    """Feed a subprocess's output lines into a queue; None marks the end."""
    try:
        for line in stream:
            lines.put(line)
    finally:
        lines.put(None)


def _plain(text: str) -> str:
    """Drop terminal escapes: OSC 8 hyperlinks (which wrap the login URL) and colour codes."""
    return _CSI_RE.sub("", _OSC_RE.sub("", text))


@shared_task(bind=True, name="tenant_runtime.run_tenant_codex_login")
def run_tenant_codex_login(self, runtime_id: str):
    """
    Launch `codex login --device-auth` as the tenant's Linux user and track it.

    Credential truth stays in CODEX_HOME. The login URL and one-time device
    code are saved for admin display only.
    """
    from cloud_agents.subprocess import run_as_argv
    from codex import service as codex_service
    from tenant_runtime.models import TenantCodexLoginSession, TenantCodexRuntime

    try:
        runtime = TenantCodexRuntime.objects.get(id=runtime_id)
    except TenantCodexRuntime.DoesNotExist:
        logger.error("[tenant_runtime] run_tenant_codex_login: runtime %s not found", runtime_id)
        return

    if not runtime.linux_user:
        logger.error("[tenant_runtime] run_tenant_codex_login: runtime %s has no linux_user", runtime_id)
        return

    session = TenantCodexLoginSession.objects.create(runtime=runtime)
    logger.info(
        "[tenant_runtime] codex login session %s starting for runtime %s (user=%s)",
        session.id,
        runtime_id,
        runtime.linux_user,
    )

    proc = None
    try:
        proc = subprocess.Popen(
            run_as_argv(
                runtime.linux_user,
                ["codex", "login", "--device-auth", "-c", 'cli_auth_credentials_store="file"'],
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={
                "HOME": runtime.home_dir,
                "CODEX_HOME": runtime.codex_home_dir,
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            },
        )

        stdout_lines = []
        url_found = False
        code_found = False

        for line in proc.stdout:
            line = line.rstrip()
            stdout_lines.append(line)
            if len(stdout_lines) > 200:
                stdout_lines = stdout_lines[-200:]

            if not url_found:
                match = _URL_RE.search(line)
                if match:
                    session.login_url = match.group(0)
                    url_found = True

            if not code_found:
                match = _DEVICE_CODE_RE.search(line)
                if match:
                    session.login_code = match.group(0)
                    code_found = True

            if url_found or code_found:
                session.status = TenantCodexLoginSession.STATUS_AWAITING_AUTH
                session.save(update_fields=["login_url", "login_code", "status"])

            if session.is_expired:
                logger.warning("[tenant_runtime] codex login session %s expired", session.id)
                proc.terminate()
                break

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        if session.is_expired:
            session.status = TenantCodexLoginSession.STATUS_EXPIRED
            session.error = "Login TTL expired before authentication completed."
            session.save(update_fields=["status", "error"])
            runtime.status = TenantCodexRuntime.STATUS_FAILED
            runtime.last_verification_error = "Login session expired."
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        if proc.returncode != 0:
            error_snippet = "\n".join(stdout_lines[-20:])[:1000]
            logger.warning(
                "[tenant_runtime] codex login exited %s session=%s output=%r",
                proc.returncode,
                session.id,
                error_snippet,
            )
            session.status = TenantCodexLoginSession.STATUS_FAILED
            session.error = f"Exit code {proc.returncode}. Output: {error_snippet}"
            session.save(update_fields=["status", "error"])
            runtime.status = TenantCodexRuntime.STATUS_FAILED
            runtime.last_verification_error = session.error[:500]
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        status_result = codex_service.login_status(
            run_as_user=runtime.linux_user,
            home_dir=runtime.home_dir,
        )
        if status_result.failure:
            session.status = TenantCodexLoginSession.STATUS_FAILED
            session.error = f"Login status failed: {status_result.failure}."
            session.save(update_fields=["status", "error"])
            runtime.status = TenantCodexRuntime.STATUS_LOGIN_REQUIRED
            runtime.last_verification_error = session.error
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        preflight = codex_service.run_blocking(
            "say ok",
            cwd=runtime.home_dir,
            run_as_user=runtime.linux_user,
            home_dir=runtime.home_dir,
            timeout=30,
            policy="read_only",
            ephemeral=True,
        )
        if preflight.failure:
            session.status = TenantCodexLoginSession.STATUS_FAILED
            session.error = f"Pre-flight verification failed: {preflight.failure}."
            session.save(update_fields=["status", "error"])
            runtime.status = (
                TenantCodexRuntime.STATUS_LOGIN_REQUIRED
                if preflight.failure == "auth_failure"
                else TenantCodexRuntime.STATUS_FAILED
            )
            runtime.last_verification_error = session.error
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        now = timezone.now()
        session.status = TenantCodexLoginSession.STATUS_COMPLETE
        session.completed_at = now
        session.save(update_fields=["status", "completed_at"])

        runtime.status = TenantCodexRuntime.STATUS_READY
        runtime.last_verified_at = now
        runtime.last_verification_error = ""
        runtime.save(update_fields=["status", "last_verified_at", "last_verification_error", "updated_at"])
        logger.info("[tenant_runtime] codex runtime %s is ready", runtime_id)

    except Exception as exc:
        logger.exception("[tenant_runtime] run_tenant_codex_login unexpected error session=%s", session.id)
        session.status = TenantCodexLoginSession.STATUS_FAILED
        session.error = str(exc)[:500]
        session.save(update_fields=["status", "error"])
        runtime.status = TenantCodexRuntime.STATUS_FAILED
        runtime.last_verification_error = str(exc)[:500]
        runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()


def verify_claude_runtime(runtime) -> str:
    """
    Check a runtime's sign-in with `claude auth status` (no model call) and record it.

    Returns "ready", "needs_sign_in" or "unknown". Readiness is only ever *granted* by
    the login task's preflight; this check can confirm it or take it away, never give it.
    """
    from claude.service import auth_status
    from tenant_runtime.models import TenantClaudeRuntime

    if not runtime.linux_user:
        return "unknown"
    status = auth_status(runtime.linux_user, runtime.home_dir)
    if status is None:
        runtime.last_verification_error = "Could not check the sign-in (the CLI did not answer)."
        runtime.save(update_fields=["last_verification_error", "updated_at"])
        return "unknown"
    if status.get("loggedIn") is True:
        if runtime.status == TenantClaudeRuntime.STATUS_READY:
            runtime.last_verified_at = timezone.now()
            runtime.last_verification_error = ""
            runtime.save(update_fields=["last_verified_at", "last_verification_error", "updated_at"])
            return "ready"
        return "unknown"
    runtime.status = TenantClaudeRuntime.STATUS_LOGIN_REQUIRED
    runtime.last_verification_error = "Signed out or sign-in expired."
    runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
    return "needs_sign_in"


@shared_task(name="tenant_runtime.check_ready_claude_runtimes")
def check_ready_claude_runtimes():
    """Daily: every READY Claude runtime is still signed in, or moves to login_required."""
    from tenant_runtime.models import TenantClaudeRuntime

    results = {}
    for runtime in TenantClaudeRuntime.objects.filter(status=TenantClaudeRuntime.STATUS_READY):
        try:
            results[str(runtime.id)] = verify_claude_runtime(runtime)
        except Exception:
            logger.exception("[tenant_runtime] check failed for runtime %s", runtime.id)
            results[str(runtime.id)] = "error"
    logger.info("[tenant_runtime] daily runtime check: %s", results)
    return results


@shared_task(name="tenant_runtime.check_claude_runtime")
def check_claude_runtime(runtime_id: str) -> str:
    """
    verify_claude_runtime, on the runtime worker (routed in celery_app).

    The web process can't run the CLI as a pool user: it runs with
    NoNewPrivileges, which forbids sudo. So Settings' "check" asks this task.
    """
    from tenant_runtime.models import TenantClaudeRuntime

    try:
        runtime = TenantClaudeRuntime.objects.get(id=runtime_id)
    except TenantClaudeRuntime.DoesNotExist:
        return "unknown"
    return verify_claude_runtime(runtime)


@shared_task(name="tenant_runtime.sign_out_claude_runtime")
def sign_out_claude_runtime(runtime_id: str) -> bool:
    """`claude auth logout` as the runtime's user, on the runtime worker. True on success."""
    from claude.service import logout
    from tenant_runtime.models import TenantClaudeRuntime

    try:
        runtime = TenantClaudeRuntime.objects.get(id=runtime_id)
    except TenantClaudeRuntime.DoesNotExist:
        return False
    if not runtime.linux_user:
        return False
    return logout(runtime.linux_user, runtime.home_dir)
