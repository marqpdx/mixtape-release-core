from __future__ import annotations

import time
from uuid import UUID

import jwt
import requests
from django.conf import settings


class AgentStackroomError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.body = body


def _mint_stackroom_service_token(subject: str = "django") -> str:
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    aud = getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir")
    claims = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        "aud": aud,
    }
    return jwt.encode(
        claims,
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


def retrieve_from_stackroom(
    *,
    query: str,
    library_id: UUID,
    limit: int = 8,
    artifact_types: list[str] | None = None,
) -> list[dict]:
    """
    Query the Stackroom vector index for a sponsor's library.

    Returns a list of result dicts with keys:
        text, score, artifact_type, artifact_id, source_file_id
    Raises AgentStackroomError on any failure.
    """
    base_url = getattr(settings, "STACKROOM_BASE_URL", "http://127.0.0.1:8012").rstrip("/")
    payload: dict = {
        "query": query,
        "library_id": str(library_id),
        "limit": limit,
    }
    if artifact_types:
        payload["artifact_types"] = artifact_types

    try:
        response = requests.post(
            f"{base_url}/service/retrieve",
            json=payload,
            headers={"X-Service-Token": _mint_stackroom_service_token()},
            timeout=30,
        )
    except requests.exceptions.ReadTimeout as exc:
        raise AgentStackroomError("Stackroom retrieve timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise AgentStackroomError(f"Stackroom unreachable: {exc}", status_code=502) from exc

    if response.status_code == 400:
        # no_embeddings or indexing_in_progress — return empty gracefully
        return []
    if response.status_code != 200:
        raise AgentStackroomError(
            "Stackroom error",
            status_code=response.status_code,
            body=response.text,
        )

    data = response.json()
    return [
        {
            "text": r.get("text", ""),
            "score": r.get("score", 0.0),
            "artifact_type": r.get("artifact_type", ""),
            "artifact_id": r.get("artifact_id", ""),
            "source_file_id": r.get("source_file_id", ""),
        }
        for r in data.get("results", [])
    ]
