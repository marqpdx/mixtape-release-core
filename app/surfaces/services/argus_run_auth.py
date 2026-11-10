# surfaces/services/argus_run_auth.py
#
# Core -> Cass's Switchboard auth for the two argus.* tools (ADR-0064 AC-5).
# Mints a short-lived token with its own secret, ARGUS_RUN_JWT_SECRET --
# deliberately not SERVICE_JWT_SECRET, which authenticates every internal
# caller of core and is never minted *by* core for an outbound call. The
# mirror image of app/ariadne/auth.py's AriadnePublishAuthentication (there
# Cass mints, Crossroads verifies; here Crossroads mints, Cass's Switchboard
# verifies -- app/services/argus_run_auth.py in mixtape-release-switchboard).
# Raises loudly if the secret is unset: there is no fallback secret to try.
#
# Not yet called anywhere: the HTTP client that would use this token waits
# on AC-3 (WireGuard). This exists now so the auth half of AC-5 is built and
# tested ahead of the network half.

from __future__ import annotations

import time

import jwt
from django.conf import settings


class ArgusRunAuthError(RuntimeError):
    """Raised when ARGUS_RUN_JWT_SECRET isn't configured."""


def mint_argus_run_token(subject: str = "core") -> str:
    secret = getattr(settings, "ARGUS_RUN_JWT_SECRET", None)
    if not secret:
        raise ArgusRunAuthError(
            "ARGUS_RUN_JWT_SECRET is not configured; refusing to mint a token "
            "rather than falling back to SERVICE_JWT_SECRET or any other secret."
        )

    now = int(time.time())
    ttl = int(getattr(settings, "ARGUS_RUN_JWT_TTL_SECONDS", 120))
    claims = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "iss": getattr(settings, "ARGUS_RUN_JWT_ISS", "crossroads-core"),
        "aud": getattr(settings, "ARGUS_RUN_JWT_AUD", "cass-switchboard-argus"),
    }
    return jwt.encode(
        claims,
        secret,
        algorithm=getattr(settings, "ARGUS_RUN_JWT_ALG", "HS256"),
    )
