import logging

from django.core.cache import cache
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

logger = logging.getLogger(__name__)

_JTI_KEY = "jti_denylist:{}"


def add_jti_to_denylist(jti: str, ttl_seconds: int) -> None:
    cache.set(_JTI_KEY.format(jti), "1", timeout=ttl_seconds)
    logger.info("JTI added to denylist: %s (ttl=%ds)", jti[:8], ttl_seconds)


def jti_is_denylisted(jti: str) -> bool:
    return cache.get(_JTI_KEY.format(jti)) is not None


class DenylistJWTAuthentication(JWTAuthentication):
    """Rejects tokens whose JTI was denylisted at logout."""

    def get_validated_token(self, raw_token):
        validated = super().get_validated_token(raw_token)
        jti = validated.get("jti")
        if jti and jti_is_denylisted(jti):
            raise InvalidToken("Token has been revoked.")
        return validated
