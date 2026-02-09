# inkwell/client.py
#
# Server-side HTTP client for the Inkwell FastAPI microservice.
# Stateless functions with typed I/O — each maps naturally to an MCP tool.

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60


class InkwellUnavailableError(Exception):
    """Raised when the Inkwell service is unreachable or not ready."""


def _base_url() -> str:
    return getattr(settings, "INKWELL_BASE_URL", "https://inkwell.crossroads.place").rstrip("/")


def is_available() -> bool:
    """Check Inkwell /health/ready endpoint. Returns True only if models are loaded."""
    try:
        resp = requests.get(f"{_base_url()}/health/ready", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("status") == "ready"
        return False
    except requests.RequestException:
        return False


def summarize(text: str, words: int = 60, style: str = "neutral") -> dict:
    """
    POST /v1/summarize → full response with summary, method, word_count, etc.

    Returns: {summary, word_count, original_word_count, target_words, style, method, explanations}
    """
    try:
        resp = requests.post(
            f"{_base_url()}/v1/summarize",
            json={"text": text, "words": words, "style": style},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/summarize timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /v1/summarize error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /v1/summarize returned {resp.status_code}")

    return resp.json()


def summarize_quick(text: str, words: int = 60) -> str:
    """
    POST /v1/summarize/quick → summary string only.

    Returns: plain summary text.
    """
    try:
        resp = requests.post(
            f"{_base_url()}/v1/summarize/quick",
            json={"text": text, "words": words},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/summarize/quick timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /v1/summarize/quick error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /v1/summarize/quick returned {resp.status_code}")

    return resp.json().get("summary", "")


def analyze(current_text: str, previous_text: str = None) -> dict:
    """
    POST /v1/analyze → {word_count, readability, paragraph_structure, changed_blocks, notes}
    """
    payload = {"current_text": current_text}
    if previous_text:
        payload["previous_text"] = previous_text

    try:
        resp = requests.post(
            f"{_base_url()}/v1/analyze",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/analyze timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /v1/analyze error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /v1/analyze returned {resp.status_code}")

    return resp.json()


def generate_metadata(text: str, max_tags: int = 5, candidate_tags: list = None) -> dict:
    """
    POST /v1/metadata → {tags, category, title, dek, blurb_140, email_snippet, explanations}
    """
    payload = {"text": text, "max_tags": max_tags}
    if candidate_tags:
        payload["candidate_tags"] = candidate_tags

    try:
        resp = requests.post(
            f"{_base_url()}/v1/metadata",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/metadata timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /v1/metadata error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /v1/metadata returned {resp.status_code}")

    return resp.json()
