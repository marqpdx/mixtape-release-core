# tenant_runtime/api/views.py
"""
Admin-only API for managing per-tenant Claude runtimes.

All views require IsAdminUser. These endpoints are not exposed to end users —
they are for Crossroads staff to configure and monitor tenant AI runtimes.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _get_group(slug: str):
    from groups.models.group import Group
    return Group.objects.filter(slug=slug, is_active=True).first()


def _get_runtime_for_group(group):
    from tenant_runtime.models import TenantClaudeRuntime
    ct = ContentType.objects.get_for_model(group)
    return TenantClaudeRuntime.objects.filter(
        tenant_content_type=ct,
        tenant_object_id=group.id,
    ).first()


class TenantRuntimeStartLoginView(APIView):
    """
    POST /api/tenant-runtime/groups/<slug>/start-login/

    Queues the run_tenant_claude_login Celery task for the tenant's runtime.
    Returns the login session ID and initial status so the client can begin polling.

    Requires: runtime exists and linux_user is set.
    """
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, slug):
        from tenant_runtime.models import TenantClaudeRuntime
        from tenant_runtime.tasks import run_tenant_claude_login

        group = _get_group(slug)
        if not group:
            return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)

        runtime = _get_runtime_for_group(group)
        if not runtime:
            return Response(
                {"detail": "No TenantClaudeRuntime configured for this group."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not runtime.linux_user:
            return Response(
                {"detail": "Runtime has no linux_user configured."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task = run_tenant_claude_login.delay(str(runtime.id))
        logger.info(
            "[tenant_runtime] start-login queued: group=%s runtime=%s task=%s",
            slug, runtime.id, task.id,
        )

        return Response({
            "task_id": task.id,
            "runtime_id": str(runtime.id),
            "status": "starting",
            "detail": "Login task queued. Poll login-status for the URL.",
        }, status=status.HTTP_202_ACCEPTED)


class TenantRuntimeLoginStatusView(APIView):
    """
    GET /api/tenant-runtime/groups/<slug>/login-status/

    Returns the most recent TenantClaudeLoginSession for this runtime,
    including the login URL once it is available.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, slug):
        group = _get_group(slug)
        if not group:
            return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)

        runtime = _get_runtime_for_group(group)
        if not runtime:
            return Response(
                {"detail": "No TenantClaudeRuntime configured for this group."},
                status=status.HTTP_404_NOT_FOUND,
            )

        session = runtime.login_sessions.order_by("-started_at").first()
        if not session:
            return Response({
                "runtime_status": runtime.status,
                "session": None,
            })

        return Response({
            "runtime_status": runtime.status,
            "session": {
                "id": str(session.id),
                "status": session.status,
                "login_url": session.login_url or None,
                "started_at": session.started_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
                "is_expired": session.is_expired,
                "error": session.error or None,
            },
        })


class TenantRuntimeStatusView(APIView):
    """
    GET /api/tenant-runtime/groups/<slug>/status/

    Returns the current TenantClaudeRuntime record for this group.
    Useful for showing runtime readiness state in admin dashboards.
    """
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, slug):
        group = _get_group(slug)
        if not group:
            return Response({"detail": "Group not found."}, status=status.HTTP_404_NOT_FOUND)

        runtime = _get_runtime_for_group(group)
        if not runtime:
            return Response({
                "configured": False,
                "detail": "No TenantClaudeRuntime configured for this group.",
            })

        return Response({
            "configured": True,
            "id": str(runtime.id),
            "provider": runtime.provider,
            "linux_user": runtime.linux_user,
            "status": runtime.status,
            "privacy_mode": runtime.privacy_mode,
            "allowed_ai_modes": runtime.allowed_ai_modes,
            "last_verified_at": runtime.last_verified_at.isoformat() if runtime.last_verified_at else None,
            "last_verification_error": runtime.last_verification_error or None,
        })
