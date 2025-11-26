from rest_framework.permissions import BasePermission

class HasChatWriteScope(BasePermission):
    def has_permission(self, request, view):
        payload = getattr(request, "auth_payload", {}) or {}
        scopes = set(payload.get("scopes", []))
        return "chat:write" in scopes
