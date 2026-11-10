# switchboard/auth.py
"""Switchboard -> core auth for exactly five endpoints (ADR-0064 AC-5a,
CTO-approved direction, 2026-11-10):

    POST   /api/switchboard/authorize            authorization:read
    POST   /api/switchboard/resolve-mcp-token     mcp:resolve
    POST   /api/initiatives/action-runs           orchestration:write
    PATCH  /api/initiatives/action-runs/{id}      orchestration:write
    GET    /api/ariadne/concepts/[...]            concept:lookup

Deliberately separate from `livewire.auth.InternalServiceAuthentication`
and `ariadne.auth.ConceptLookupServiceAuthentication`: both of those check
against `SERVICE_JWT_SECRET`, which authenticates *every* internal caller
of core (chat, dispatch, Inkwell, Livewire). A copy of that secret on a
second host (Cass, under AC-1) would let anyone there mint a token for any
of those callers, not just Switchboard's. This verifier checks only
`SWITCHBOARD_CORE_JWT_SECRETS` -- its own secret(s), its own audience --
and is additive to the two authenticators named in this repo's CLAUDE.md,
not a third general-purpose one (see that file's Internal Service Auth
Conventions section).

Crossroads' and Cass's Switchboard each mint with their own secret value
and their own `kid` (JWT header) under `SWITCHBOARD_CORE_JWT_SECRETS`
(mixtape-release-switchboard/app/services/switchboard_core_auth.py mints
these). Looking the secret up by `kid` means either deployment's
credential can be rotated or revoked without touching the other's. Fails
closed throughout: no configured secrets, an unrecognized `kid`, or a
malformed/expired/wrong-scope token all return `None` (refuse) rather than
falling back to `SERVICE_JWT_SECRET` or any other shared secret.

Isolation between the five routes above comes from the `scopes` claim, not
a separate audience per route -- callers use the scope permission classes
in `initiatives.api.permissions` / `switchboard.api.permissions` the same
way `InternalServiceAuthentication`'s callers already do. The one
exception is `concept:lookup`: that route needs a real Django user (its
`IsSuperuser` check runs against `request.user`, not a claim), so `sub` is
resolved to a user and returned as the authenticated principal instead of
`AnonymousUser()` -- mirrors `ConceptLookupServiceAuthentication`'s shape,
which this replaces for that one route.
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
        if token:
            return token

    header_token = request.headers.get("X-Service-Token", "").strip()
    return header_token or None


class SwitchboardCoreAuthentication(BaseAuthentication):
    """Verifies against SWITCHBOARD_CORE_JWT_SECRETS, keyed by the token's
    `kid` header. Returns `(AnonymousUser(), payload)` for every scope
    except `concept:lookup`, which resolves `sub` to a real user instead."""

    def authenticate(self, request):
        secrets_by_kid = getattr(settings, "SWITCHBOARD_CORE_JWT_SECRETS", None) or {}
        if not secrets_by_kid:
            return None

        token = _extract_token(request)
        if not token:
            return None

        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError:
            return None

        secret = secrets_by_kid.get(kid)
        if not secret:
            return None

        alg = getattr(settings, "SWITCHBOARD_CORE_JWT_ALG", "HS256")
        iss = getattr(settings, "SWITCHBOARD_CORE_JWT_ISS", "mixtape")
        aud = getattr(settings, "SWITCHBOARD_CORE_JWT_AUD", "switchboard-core")

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

        request.auth_payload = payload

        if "concept:lookup" in payload.get("scopes", []):
            try:
                user = User.objects.get(pk=payload["sub"])
            except (User.DoesNotExist, ValueError, TypeError):
                return None
            return (user, payload)

        request.service_principal = payload
        return (AnonymousUser(), payload)
