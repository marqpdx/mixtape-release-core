"""
Ariadne -- Cass-to-Crossroads publish flow's own service authentication
(decisions/ariadne/build-plan-cass-to-crossroads-result-flow.md, Headnote
2026-11-07; zz/_handoffs/handoff-2026-11-07-blue-ariadne-publish-secret.md).

Deliberately separate from `livewire.auth.InternalServiceAuthentication`:
that authenticator checks every internal service token against one shared
`SERVICE_JWT_SECRET`, with the scope carried as a claim inside the token.
A copy of that secret on Cass would let anyone on Cass mint a production
token for *any* internal service, not just this one. This flow signs and
verifies with its own secret, audience and issuer instead, so a token
minted here can't pass as any other service's token and vice versa.
`InternalServiceAuthentication` and its other callers are untouched.
"""

from __future__ import annotations

import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication, get_authorization_header


def _extract_token(request) -> str | None:
    auth = get_authorization_header(request).split()
    if auth and auth[0].lower() == b"bearer":
        token = auth[1].decode("utf-8") if len(auth) > 1 else ""
        return token or None

    header_token = request.headers.get("X-Service-Token", "").strip()
    return header_token or None


class AriadnePublishAuthentication(BaseAuthentication):
    """Verifies only against ARIADNE_PUBLISH_JWT_*. Fails closed: if the
    secret isn't configured, every request is refused -- never falls back
    to SERVICE_JWT_SECRET or any other shared secret."""

    def authenticate(self, request):
        secret = getattr(settings, "ARIADNE_PUBLISH_JWT_SECRET", None)
        if not secret or not isinstance(secret, str):
            return None

        token = _extract_token(request)
        if not token:
            return None

        alg = getattr(settings, "ARIADNE_PUBLISH_JWT_ALG", "HS256")
        iss = getattr(settings, "ARIADNE_PUBLISH_JWT_ISS", "cass-ariadne")
        aud = getattr(settings, "ARIADNE_PUBLISH_JWT_AUD", "crossroads-ariadne-import")

        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[alg],
                issuer=iss,
                audience=aud,
                options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
            )
        except (jwt.PyJWTError, TypeError):
            return None

        request.auth_payload = payload
        request.service_principal = payload
        return (AnonymousUser(), payload)


# ConceptLookupServiceAuthentication removed 2026-11-10 (ADR-0064 AC-5a):
# folded onto SWITCHBOARD_CORE_JWT_SECRETS as a 5th scoped endpoint. See
# switchboard/auth.py's SwitchboardCoreAuthentication, now used by
# ariadne/api/views.py's ConceptLookupView in its place.
