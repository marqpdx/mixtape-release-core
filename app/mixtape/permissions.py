"""
DRF permission classes for tenant enforcement.

TenantContextRequired returns HTTP 428 Precondition Required when a request
does not carry a resolved tenant. HTTP 428 specifically (not 403 or 400) so
this failure mode remains separately visible in logs, dashboards, and alerting.

Usage:
    class SomeView(APIView):
        permission_classes = [IsAuthenticated, TenantContextRequired]
"""
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission


class MissingTenantContext(APIException):
    status_code = status.HTTP_428_PRECONDITION_REQUIRED
    default_detail = "Request does not carry a resolved tenant context."
    default_code = "missing_tenant_context"


class TenantContextRequired(BasePermission):
    """
    Raises HTTP 428 if request.tenant is not set.

    Apply to any view that operates on tenant-scoped data.
    Do not apply to global routes: admin, ops dashboards, health checks.
    """

    def has_permission(self, request, view):
        if not getattr(request, "tenant", None):
            raise MissingTenantContext()
        return True
