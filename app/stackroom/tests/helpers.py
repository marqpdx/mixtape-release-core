# stackroom/tests/helpers.py

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import jwt
from django.conf import settings
from django.core import mail


def clear_emails() -> None:
    try:
        mail.outbox.clear()
    except Exception:
        pass


def last_email() -> Optional[Any]:
    try:
        return mail.outbox[-1] if mail.outbox else None
    except Exception:
        return None


def mint_stackroom_service_token(
    *,
    user_id: str,
    secret: Optional[str] = None,
    iss: Optional[str] = None,
    aud_ir: Optional[str] = None,
    alg: str = "HS256",
    lifetime_sec: int = 600,
    nbf_skew_sec: int = 5,
) -> str:
    secret = secret if secret is not None else getattr(settings, "SERVICE_JWT_SECRET", "")
    iss = iss if iss is not None else getattr(settings, "SERVICE_JWT_ISS", "mixtape")
    aud_ir = aud_ir if aud_ir is not None else getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir")

    if not secret:
        raise RuntimeError("SERVICE_JWT_SECRET must be set for tests that mint service JWTs")

    now = int(time.time())
    payload: Dict[str, Any] = {
        "iss": iss,
        "aud": aud_ir,
        "sub": str(user_id),
        "iat": now,
        "nbf": now - nbf_skew_sec,
        "exp": now + lifetime_sec,
        "svc": "stackroom",
        "scope": "stackroom.ir.write",
    }
    return jwt.encode(payload, secret, algorithm=alg)
