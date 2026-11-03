# tenant_runtime/api/person_views.py
"""
Your own AI accounts: connect, sign in, check and disconnect (Service Trust ST-3).

Every view finds the runtime from request.user alone. No route takes a runtime id
or a username, so nobody can see or start another person's sign-in, staff
included (decision S5). Responses never include the Linux user or paths.

Mounted at /api/me/ai-accounts/.
"""

import logging
import re

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from tenant_runtime import pool
from tenant_runtime.models import TenantClaudeLoginSession, TenantClaudeRuntime
from tenant_runtime.resolve import CLAUDE, ensure_person_runtime, get_person_runtime

logger = logging.getLogger(__name__)

_ACTIVE_LOGIN = (TenantClaudeLoginSession.STATUS_STARTING, TenantClaudeLoginSession.STATUS_AWAITING_AUTH)

# A sign-in code: printable ASCII with no spaces, so it can't carry a second line to the CLI.
_SIGN_IN_CODE_RE = re.compile(r"[\x21-\x7e]{8,512}")

# How long a check or sign-out waits for the runtime worker before saying so.
RUNTIME_ANSWER_SECONDS = 45


def _on_runtime_worker(task, runtime_id: str):
    """
    Run a CLI task on the runtime worker and wait for its answer; None if none came.

    The web process runs with NoNewPrivileges, which forbids sudo, so it can't run
    the CLI as a pool user itself (ST-3). The task is routed to the "runtime" queue,
    whose worker alone may.
    """
    try:
        return task.apply_async(args=[runtime_id]).get(timeout=RUNTIME_ANSWER_SECONDS)
    except Exception:
        logger.exception("[tenant_runtime] %s got no answer from the runtime worker", task.name)
        return None


def _active_login(runtime):
    session = runtime.login_sessions.order_by("-started_at").first()
    if session and session.status in _ACTIVE_LOGIN and not session.is_expired:
        return session
    return None


def _claude_state(runtime) -> dict:
    if runtime is None:
        return {"state": "none"}
    if _active_login(runtime):
        state = "connecting"
    elif runtime.status == TenantClaudeRuntime.STATUS_READY:
        state = "ready"
    elif runtime.status == TenantClaudeRuntime.STATUS_FAILED:
        state = "failed"
    else:
        state = "needs_sign_in"
    return {
        "state": state,
        "last_checked": runtime.last_verified_at.isoformat() if runtime.last_verified_at else None,
        "message": runtime.last_verification_error or None,
    }


class MyAIAccountsView(APIView):
    """GET /api/me/ai-accounts/ — the state of each of your AI accounts."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            "claude": _claude_state(get_person_runtime(request.user, CLAUDE)),
            # Codex follows under F3; not offered to people yet.
            "codex": {"state": "not_available"},
        })


class MyClaudeConnectView(APIView):
    """POST /api/me/ai-accounts/claude/connect/ — create your runtime if needed and start sign-in."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from tenant_runtime.tasks import run_tenant_claude_login

        try:
            runtime = ensure_person_runtime(request.user, CLAUDE)
        except pool.PoolError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if _active_login(runtime):
            return Response(_claude_state(runtime), status=status.HTTP_409_CONFLICT)

        # A new attempt: last time's error no longer describes it.
        if runtime.last_verification_error:
            runtime.last_verification_error = ""
            runtime.save(update_fields=["last_verification_error", "updated_at"])
        task = run_tenant_claude_login.delay(str(runtime.id))
        logger.info("[tenant_runtime] person sign-in queued: user=%s runtime=%s task=%s",
                    request.user.pk, runtime.id, task.id)
        return Response({"state": "connecting"}, status=status.HTTP_202_ACCEPTED)


class MyClaudeLoginView(APIView):
    """GET /api/me/ai-accounts/claude/login/ — your latest sign-in: the link to open, and its status."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        runtime = get_person_runtime(request.user, CLAUDE)
        session = runtime.login_sessions.order_by("-started_at").first() if runtime else None
        if session is None:
            return Response({"session": None, **_claude_state(runtime)})
        return Response({
            **_claude_state(runtime),
            "session": {
                "status": session.status,
                "login_url": session.login_url or None,
                "expires_at": session.expires_at.isoformat(),
                "is_expired": session.is_expired,
                "error": session.error or None,
            },
        })


class MyClaudeLoginCodeView(APIView):
    """
    POST /api/me/ai-accounts/claude/login/code/ — the code Anthropic showed you after you approved.

    Accepted only for your own sign-in that is showing its link. The login task on the
    runtime worker types it into the waiting CLI and clears it within seconds. The code
    is never logged and never sent back.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        code = request.data.get("code")
        code = code.strip() if isinstance(code, str) else ""
        if not _SIGN_IN_CODE_RE.fullmatch(code):
            return Response(
                {"detail": "That doesn't look like a sign-in code. Copy it again from the Claude page."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        runtime = get_person_runtime(request.user, CLAUDE)
        session = _active_login(runtime) if runtime else None
        if session is None or session.status != TenantClaudeLoginSession.STATUS_AWAITING_AUTH:
            return Response(
                {"detail": "There's no sign-in waiting for a code. Start again with Sign in."},
                status=status.HTTP_409_CONFLICT,
            )
        # Only an empty slot takes a code, so a second paste can't replace one in flight.
        taken = TenantClaudeLoginSession.objects.filter(pk=session.pk, pending_code="").update(pending_code=code)
        if not taken:
            return Response(
                {"detail": "A code is already on its way. Give it a moment."},
                status=status.HTTP_409_CONFLICT,
            )
        logger.info("[tenant_runtime] sign-in code received: user=%s session=%s", request.user.pk, session.id)
        return Response({"state": "connecting"}, status=status.HTTP_202_ACCEPTED)


class MyClaudeCheckView(APIView):
    """POST /api/me/ai-accounts/claude/check/ — check your sign-in now (no model call)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from tenant_runtime.tasks import check_claude_runtime

        runtime = get_person_runtime(request.user, CLAUDE)
        if runtime is None:
            return Response({"state": "none"}, status=status.HTTP_404_NOT_FOUND)
        if _on_runtime_worker(check_claude_runtime, str(runtime.id)) is None:
            return Response(
                {**_claude_state(runtime), "detail": "Couldn't check your sign-in just now. Try again in a minute."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        runtime.refresh_from_db()
        return Response(_claude_state(runtime))


class MyClaudeDisconnectView(APIView):
    """POST /api/me/ai-accounts/claude/disconnect/ — sign out; nothing runs on your account until you sign in again."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from tenant_runtime.tasks import sign_out_claude_runtime

        runtime = get_person_runtime(request.user, CLAUDE)
        if runtime is None:
            return Response({"state": "none"})
        # Not ready first, so no queued work starts on the account while it signs out.
        runtime.status = TenantClaudeRuntime.STATUS_LOGIN_REQUIRED
        runtime.last_verification_error = "Disconnected."
        runtime.save(update_fields=["status", "last_verification_error", "updated_at"])
        if not _on_runtime_worker(sign_out_claude_runtime, str(runtime.id)):
            runtime.last_verification_error = "Disconnected here, but signing out of Claude did not complete."
            runtime.save(update_fields=["last_verification_error", "updated_at"])
            return Response(_claude_state(runtime), status=status.HTTP_502_BAD_GATEWAY)
        return Response(_claude_state(runtime))
