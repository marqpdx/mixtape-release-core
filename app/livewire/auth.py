# livewire/auth.py

import logging

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header


log = logging.getLogger(__name__)

User = get_user_model()

class ServiceJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b"bearer":
            return None

        token = auth[1].decode("utf-8") if len(auth) > 1 else ""
        if not token:
            return None  # let next authenticator try

        # 🔹 Guard: if SERVICE_JWT_SECRET is missing or not a string, skip
        service_secret = getattr(settings, "SERVICE_JWT_SECRET", None)
        if not service_secret or not isinstance(service_secret, str):
            # Misconfigured service secret – do NOT blow up normal requests
            # log.warning("ServiceJWTAuthentication skipped: invalid SERVICE_JWT_SECRET (%r)", service_secret)
            return None

        alg = getattr(settings, "SERVICE_JWT_ALG", "HS256")
        iss = getattr(settings, "SERVICE_JWT_ISS", "mixtape")
        aud = getattr(settings, "SERVICE_JWT_AUD", "django-api")

        try:
            payload = jwt.decode(
                token,
                service_secret,
                algorithms=[alg],
                issuer=iss,
                audience=aud,
                options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
            )

        except (jwt.PyJWTError, TypeError):
            # Not a valid *service* token – let the next authenticator try.
            # log.warning("ServiceJWTAuthentication reject: %s", e)
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


