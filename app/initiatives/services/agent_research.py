from __future__ import annotations

import requests
from django.conf import settings

from inkwell.client import InkwellUnavailableError, _mint_inkwell_service_token


class AgentResearchError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.body = body


def summarize_via_inkwell(*, text: str, words: int = 60, style: str = "neutral") -> str:
    """
    Call Inkwell's /service/summarize endpoint and return the summary string.
    Raises AgentResearchError on failure.
    """
    base_url = getattr(settings, "INKWELL_BASE_URL", "").rstrip("/") or "https://inkwell.crossroads.place"
    payload = {"text": text, "words": words, "style": style}

    try:
        token = _mint_inkwell_service_token(subject="switchboard")
    except InkwellUnavailableError as exc:
        raise AgentResearchError(str(exc), status_code=503) from exc

    try:
        response = requests.post(
            f"{base_url}/service/summarize",
            json=payload,
            headers={"X-Service-Token": token},
            timeout=60,
        )
    except requests.exceptions.ReadTimeout as exc:
        raise AgentResearchError("Inkwell summarize timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise AgentResearchError(f"Inkwell unreachable: {exc}", status_code=502) from exc

    if response.status_code != 200:
        raise AgentResearchError(
            "Inkwell summarize error",
            status_code=response.status_code,
            body=response.text,
        )

    return response.json().get("summary") or ""


def research_via_inkwell(*, query: str) -> dict:
    """
    Call Inkwell's /v1/research/research endpoint and return the response dict.

    Returns a dict with keys: result, type, query, sources, word_count, confidence, method.
    Raises AgentResearchError on any failure.
    """
    base_url = getattr(settings, "INKWELL_BASE_URL", "").rstrip("/") or "https://inkwell.crossroads.place"
    payload = {
        "text": query,
        "type": "research",
    }

    try:
        token = _mint_inkwell_service_token(subject="switchboard")
    except InkwellUnavailableError as exc:
        raise AgentResearchError(str(exc), status_code=503) from exc

    try:
        response = requests.post(
            f"{base_url}/v1/research/research",
            json=payload,
            headers={"X-Service-Token": token},
            timeout=90,
        )
    except requests.exceptions.ReadTimeout as exc:
        raise AgentResearchError("Inkwell research timed out.", status_code=504) from exc
    except requests.RequestException as exc:
        raise AgentResearchError(f"Inkwell unreachable: {exc}", status_code=502) from exc

    if response.status_code != 200:
        raise AgentResearchError(
            "Inkwell research error",
            status_code=response.status_code,
            body=response.text,
        )

    return response.json()
