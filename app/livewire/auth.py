# livewire/auth.py

import jwt
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework import exceptions
from django.conf import settings
from django.contrib.auth import get_user_model

import logging
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

        try:
            payload = jwt.decode(
                token,
                settings.SERVICE_JWT_SECRET,
                algorithms=[getattr(settings, "SERVICE_JWT_ALG", "HS256")],
                issuer=getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
                audience=getattr(settings, "SERVICE_JWT_AUD", "django-api"),
                options={"require": ["exp","iat","nbf","iss","aud"]},
            )

        except jwt.PyJWTError as e:
            # Not a valid *service* token – just return None so JWTAuthentication can try.
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
