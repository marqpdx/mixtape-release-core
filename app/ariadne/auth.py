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
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication, get_authorization_header

User = get_user_model()


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


class ConceptLookupServiceAuthentication(BaseAuthentication):
    """Switchboard calling P6a's Concept lookup on a real person's behalf
    (handoff-2026-11-05-blue-ariadne-p9-live-p6a-folio-review.md row 2;
    agent-inbox/2026-11-07-blue-folio-contract-review-and-p6a-fork.md).

    Uses the same shared SERVICE_JWT_SECRET as `livewire.auth.ServiceJWTAuthentication`
    -- that authenticator's whole job is "a service token maps to a real Django
    user," which is exactly what this call needs (IsSuperuser checks the real
    user, not a claim). But its audience is its own, `CONCEPT_LOOKUP_JWT_AUD`,
    not the generic SERVICE_JWT_AUD every other ServiceJWTAuthentication caller
    (chat, dispatch) shares: a token minted for this one call fails everywhere
    else, so this is the only thing a leaked or misused token of this shape can
    reach. `ServiceJWTAuthentication` and its other callers are untouched --
    this is a second, Ariadne-local authenticator next to `AriadnePublishAuthentication`,
    not a change to the shared one."""

    def authenticate(self, request):
        secret = getattr(settings, "SERVICE_JWT_SECRET", None)
        if not secret or not isinstance(secret, str):
            return None

        token = _extract_token(request)
        if not token:
            return None

        alg = getattr(settings, "SERVICE_JWT_ALG", "HS256")
        iss = getattr(settings, "SERVICE_JWT_ISS", "mixtape")
        aud = getattr(settings, "CONCEPT_LOOKUP_JWT_AUD", "switchboard-concept-lookup")

        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=[alg],
                issuer=iss,
                audience=aud,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, TypeError):
            return None

        try:
            user = User.objects.get(pk=payload["sub"])
        except User.DoesNotExist:
            return None

        request.auth_payload = payload
        return (user, payload)
