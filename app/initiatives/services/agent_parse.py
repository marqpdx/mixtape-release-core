from __future__ import annotations

import time
from uuid import UUID

import jwt
import requests
from django.conf import settings


class AgentParseError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.body = body


def _mint_inkwell_service_token(subject: str = "switchboard") -> str:
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    claims = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        "aud": "django-inkwell",
    }
    return jwt.encode(
        claims,
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


def parse_agent_command(
    *,
    text: str,
    capture_mode: str,
    source: str,
    initiative_id: UUID | None,
    sponsor_model: str | None,
    sponsor_id: UUID | None,
    principal_user_id: UUID | None,
    principal_service_token_id: str | None = None,
) -> dict:
    base_url = getattr(settings, "INKWELL_BASE_URL", "").rstrip("/") or "https://inkwell.crossroads.place"
    payload = {
        "text": text,
        "capture_mode": capture_mode,
        "surface": source,
        "initiative_id": str(initiative_id) if initiative_id else None,
        "sponsor_model": sponsor_model,
        "sponsor_id": str(sponsor_id) if sponsor_id else None,
        "tenant_id": str(getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")),
        "principal_user_id": str(principal_user_id) if principal_user_id else None,
        "principal_service_token_id": principal_service_token_id,
    }

    try:
        response = requests.post(
            f"{base_url}/service/agent/parse",
            json=payload,
            headers={"X-Service-Token": _mint_inkwell_service_token()},
            timeout=60,
        )
    except requests.exceptions.ReadTimeout as exc:
        raise AgentParseError("Inkwell agent parse timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise AgentParseError(f"Inkwell unreachable: {exc}", status_code=502) from exc

    if response.status_code != 200:
        raise AgentParseError(
            "Inkwell error",
            status_code=response.status_code,
            body=response.text,
        )

    return response.json()
