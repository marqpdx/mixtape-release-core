# atrium/ai/canon_client.py
#
# Django -> Stackroom HTTP client for the Atrium read-only bridge (Stage 1).
# Same service-JWT auth pattern as inkwell/stackroom_http_client.py, scoped
# to the read-only canon-bundles endpoints (query_canon, get_document).

from __future__ import annotations

import json
import logging
import time

import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return getattr(settings, "STACKROOM_BASE_URL", "http://127.0.0.1:8012").rstrip("/")


def _mint_service_token() -> str:
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    return jwt.encode(
        {
            "sub": "django",
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
            "aud": getattr(settings, "SERVICE_JWT_AUD_IR", "django-ir"),
        },
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


def _headers() -> dict[str, str]:
    return {"X-Service-Token": _mint_service_token()}


def _canon_user_id() -> str:
    user_id = getattr(settings, "ATRIUM_CANON_USER_ID", "")
    if not user_id:
        raise RuntimeError("ATRIUM_CANON_USER_ID is not configured.")
    return user_id


def query_canon(query: str, limit: int = 5) -> str:
    """Semantic search over the canon replica. Returns a JSON string for tool_result."""
    try:
        resp = requests.post(
            f"{_base_url()}/canon-bundles/query",
            json={"user_id": _canon_user_id(), "query": query, "limit": limit},
            headers=_headers(),
            timeout=20,
        )
    except requests.RequestException as exc:
        return json.dumps({"error": f"query_canon request failed: {exc}"})

    if resp.status_code != 200:
        return json.dumps({"error": f"query_canon failed: {resp.status_code} {resp.text[:300]}"})
    return json.dumps(resp.json())


def get_document(doc_uuid: str) -> str:
    """Fetch a canon document's full text by doc_uuid. Returns a JSON string for tool_result."""
    try:
        resp = requests.get(
            f"{_base_url()}/canon-bundles/documents/{doc_uuid}",
            params={"user_id": _canon_user_id()},
            headers=_headers(),
            timeout=20,
        )
    except requests.RequestException as exc:
        return json.dumps({"error": f"get_document request failed: {exc}"})

    if resp.status_code != 200:
        return json.dumps({"error": f"get_document failed: {resp.status_code} {resp.text[:300]}"})
    return json.dumps(resp.json())
