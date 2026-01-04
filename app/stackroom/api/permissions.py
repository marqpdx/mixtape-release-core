# stackroom/api/permissions.py

from rest_framework.permissions import BasePermission


class HasStackroomIRScope(BasePermission):
    """
    Narrow permission for IR persistence.
    """
    def has_permission(self, request, view):
        payload = getattr(request, "auth_payload", None) or {}
        return payload.get("svc") == "stackroom" and payload.get("scope") == "stackroom.ir.write"
