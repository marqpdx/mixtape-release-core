# tenant_runtime/tasks.py
"""
Celery tasks for the tenant_runtime app.

run_tenant_claude_login: launches claude auth login as the tenant's Linux user,
captures the URL from stdout for display in the admin UI, and waits for exit.
"""

import logging
import subprocess

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

_LOGIN_SUBPROCESS_TIMEOUT = 610  # slightly over the 10-minute session TTL


@shared_task(bind=True, name="tenant_runtime.run_tenant_claude_login")
def run_tenant_claude_login(self, runtime_id: str):
    """
    Launch `claude auth login` as the tenant's Linux user and track the session.

    Flow:
      1. Create TenantClaudeLoginSession (status: starting).
      2. Spawn subprocess via runuser — stdout contains the login URL.
      3. Read stdout lines until a https:// URL is found; save it and set status: awaiting_auth.
      4. Wait for process exit (Anthropic server-side polling resolves the login).
      5. On exit 0: run pre-flight verification; set runtime status: ready.
      6. On non-zero exit or timeout: set session/runtime to failed/expired.
    """
    from claude.service import run_blocking
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

    proc = None
    try:
        proc = subprocess.Popen(
            ["runuser", "-u", runtime.linux_user, "--", "claude", "auth", "login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={"HOME": runtime.home_dir, "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        url_found = False
        stdout_lines = []

        for line in proc.stdout:
            line = line.rstrip()
            stdout_lines.append(line)

            if len(stdout_lines) > 200:
                stdout_lines = stdout_lines[-200:]

            if not url_found and line.strip().startswith("https://"):
                url = line.strip()
                session.login_url = url
                session.status = TenantClaudeLoginSession.STATUS_AWAITING_AUTH
                session.save(update_fields=["login_url", "status"])
                logger.info("[tenant_runtime] login URL detected session=%s", session.id)
                url_found = True

            if session.is_expired:
                logger.warning("[tenant_runtime] login session %s expired while waiting", session.id)
                proc.terminate()
                break

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        if session.is_expired:
            session.status = TenantClaudeLoginSession.STATUS_EXPIRED
            session.error = "Login TTL expired before authentication completed."
            session.save(update_fields=["status", "error"])
            runtime.status = TenantClaudeRuntime.STATUS_FAILED
            runtime.last_verification_error = "Login session expired."
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        if proc.returncode != 0:
            error_snippet = "\n".join(stdout_lines[-20:])[:1000]
            logger.warning(
                "[tenant_runtime] claude auth login exited %s session=%s output=%r",
                proc.returncode, session.id, error_snippet,
            )
            session.status = TenantClaudeLoginSession.STATUS_FAILED
            session.error = f"Exit code {proc.returncode}. Output: {error_snippet}"
            session.save(update_fields=["status", "error"])
            runtime.status = TenantClaudeRuntime.STATUS_FAILED
            runtime.last_verification_error = session.error[:500]
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        # Exit 0 — run pre-flight verification
        logger.info("[tenant_runtime] auth login exited 0, running pre-flight session=%s", session.id)
        result = run_blocking("say ok", cwd=runtime.home_dir, run_as_user=runtime.linux_user, timeout=30)

        if result.failure == "auth_failure":
            session.status = TenantClaudeLoginSession.STATUS_FAILED
            session.error = "Pre-flight verification failed: auth_failure after login completed."
            session.save(update_fields=["status", "error"])
            runtime.status = TenantClaudeRuntime.STATUS_LOGIN_REQUIRED
            runtime.last_verification_error = session.error
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
            return

        if result.failure:
            session.status = TenantClaudeLoginSession.STATUS_FAILED
            session.error = f"Pre-flight verification failed: {result.failure}."
            session.save(update_fields=["status", "error"])
            runtime.status = TenantClaudeRuntime.STATUS_FAILED
            runtime.last_verification_error = session.error
            runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
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
        session.status = TenantClaudeLoginSession.STATUS_FAILED
        session.error = str(exc)[:500]
        session.save(update_fields=["status", "error"])
        runtime.status = TenantClaudeRuntime.STATUS_FAILED
        runtime.last_verification_error = str(exc)[:500]
        runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
