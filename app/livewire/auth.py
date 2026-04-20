# livewire/auth.py

import logging

import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header


log = logging.getLogger(__name__)

User = get_user_model()


def _extract_service_token(request) -> str | None:
    auth = get_authorization_header(request).split()
    if auth and auth[0].lower() == b"bearer":
        token = auth[1].decode("utf-8") if len(auth) > 1 else ""
        if token:
            return token

    header_token = request.headers.get("X-Service-Token", "").strip()
    return header_token or None


def _decode_service_jwt(token: str) -> dict | None:
    service_secret = getattr(settings, "SERVICE_JWT_SECRET", None)
    if not service_secret or not isinstance(service_secret, str):
        return None

    alg = getattr(settings, "SERVICE_JWT_ALG", "HS256")
    iss = getattr(settings, "SERVICE_JWT_ISS", "mixtape")
    aud = getattr(settings, "SERVICE_JWT_AUD", "django-api")

    try:
        return jwt.decode(
            token,
            service_secret,
            algorithms=[alg],
            issuer=iss,
            audience=aud,
            options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
        )
    except (jwt.PyJWTError, TypeError):
        return None

class ServiceJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b"bearer":
            return None

        token = auth[1].decode("utf-8") if len(auth) > 1 else ""
        if not token:
            return None  # let next authenticator try

        payload = _decode_service_jwt(token)
        if payload is None:
            return None

        uid = payload.get("sub")
        if not uid:
            return None

        try:
            user = User.objects.get(pk=uid)
        except User.DoesNotExist:
            return None

        request.auth_payload = payload
        return (user, None)


class InternalServiceAuthentication(BaseAuthentication):
    """
    Generic internal-service authenticator.

    Unlike ServiceJWTAuthentication, this does not require the JWT subject to
    map to a Django user row. It is intended for service principals such as
    Switchboard writing ActionRuns into Django.
    """

    def authenticate(self, request):
        token = _extract_service_token(request)
        if not token:
            return None

        payload = _decode_service_jwt(token)
        if payload is None:
            return None

        request.auth_payload = payload
        request.service_principal = payload
        return (AnonymousUser(), payload)

