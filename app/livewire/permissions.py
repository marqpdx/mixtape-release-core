from rest_framework.permissions import BasePermission


class _HasServiceScope(BasePermission):
    required_scope = ""

    def has_permission(self, request, view):
        payload = getattr(request, "auth_payload", {}) or {}
        scopes = set(payload.get("scopes", []))
        return self.required_scope in scopes


class HasChatWriteScope(_HasServiceScope):
    required_scope = "chat:write"


class HasDispatchWriteScope(_HasServiceScope):
    required_scope = "dispatch:write"


class HasOrchestrationWriteScope(_HasServiceScope):
    required_scope = "orchestration:write"
