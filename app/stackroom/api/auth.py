# stackroom/api/auth.py
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication, get_authorization_header

User = get_user_model()


class ServiceJWTAuthentication(BaseAuthentication):
    """
    Verifies service tokens minted by Stackroom/Livewire/etc.
    """
    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b"bearer":
            return None

        token = auth[1].decode("utf-8") if len(auth) > 1 else ""
        if not token:
            return None

        secret = getattr(settings, "SERVICE_JWT_SECRET", None)
        if not secret or not isinstance(secret, str):
            return None

        alg = getattr(settings, "SERVICE_JWT_ALG", "HS256")
        iss = getattr(settings, "SERVICE_JWT_ISS", "mixtape")
        aud = getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir")

        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[alg],
                issuer=iss,
                audience=aud,
                options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
            )
        except jwt.PyJWTError:
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
