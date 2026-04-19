import jwt
from django.conf import settings
from rest_framework.permissions import BasePermission


def _decode_service_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.SERVICE_JWT_SECRET,
        algorithms=[getattr(settings, "SERVICE_JWT_ALG", "HS256")],
        issuer=getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        audience=getattr(settings, "SERVICE_JWT_AUD", "django-api"),
        options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
    )


class HasOrchestrationWriteScope(BasePermission):
    message = "Valid orchestration service token required."

    def has_permission(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
        elif request.headers.get("X-Service-Token"):
            token = request.headers.get("X-Service-Token", "").strip()

        if not token:
            return False

        try:
            payload = _decode_service_token(token)
        except jwt.PyJWTError:
            return False

        scopes = set(payload.get("scopes", []))
        if "orchestration:write" not in scopes:
            return False

        request.auth_payload = payload
        return True
