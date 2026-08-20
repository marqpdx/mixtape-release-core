# inkwell/client.py
#
# Server-side HTTP client for the Inkwell FastAPI microservice.
# Stateless functions with typed I/O — each maps naturally to an MCP tool.

import logging
import time

import jwt
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60


class InkwellUnavailableError(Exception):
    """Raised when the Inkwell service is unreachable or not ready."""


def _base_url() -> str:
    return getattr(settings, "INKWELL_BASE_URL", "https://inkwell.crossroads.place").rstrip("/")


def _mint_inkwell_service_token() -> str:
    secret = getattr(settings, "INKWELL_SERVICE_JWT_SECRET", None)
    if not secret:
        raise InkwellUnavailableError(
            "INKWELL_SERVICE_JWT_SECRET not configured — required for /service/* endpoints"
        )
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    return jwt.encode(
        {
            "sub": "django",
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
            "aud": getattr(settings, "INKWELL_SERVICE_JWT_AUD", "django-inkwell"),
        },
        secret,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )


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


def extract_commons(url: str) -> dict:
    """
    POST /v1/extract/commons → structured entity data.

    Returns a dict with keys: name, item_type, description, location, founder,
    website, instagram, youtube, contact_email, tags, additional_data,
    extraction_method, extraction_error, raw_text_length, source_url.

    Raises InkwellUnavailableError if the service is unreachable.
    """
    try:
        resp = requests.post(
            f"{_base_url()}/v1/extract/commons",
            json={"url": url},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/extract/commons timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error(
            "Inkwell /v1/extract/commons error %s: %s",
            resp.status_code,
            resp.text[:500],
        )
        raise InkwellUnavailableError(
            f"Inkwell /v1/extract/commons returned {resp.status_code}"
        )

    return resp.json()


def extract_research(url: str) -> dict:
    """
    POST /v1/extract/research → structured article/research data.

    Returns a dict with keys: title, author, publication, published_date,
    summary, key_themes, excerpt, additional_data, extraction_method,
    extraction_error, raw_text_length, source_url.

    Raises InkwellUnavailableError if the service is unreachable.
    """
    try:
        resp = requests.post(
            f"{_base_url()}/v1/extract/research",
            json={"url": url},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/extract/research timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error(
            "Inkwell /v1/extract/research error %s: %s",
            resp.status_code,
            resp.text[:500],
        )
        raise InkwellUnavailableError(
            f"Inkwell /v1/extract/research returned {resp.status_code}"
        )

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


def service_generate(
    *,
    prompt: str,
    system_prompt: str | None = None,
    schema: dict | None = None,
    max_tokens: int = 512,
    temperature: float = 0.1,
    timeout_seconds: int | None = None,
) -> dict:
    """
    POST /service/generate — grammar-constrained generation with optional system prompt.

    Returns the full response dict: {result, raw_text, method}.
    `result` is the parsed JSON object when `schema` is provided.
    Raises InkwellUnavailableError on any transport or auth error.

    Requires INKWELL_SERVICE_JWT_SECRET in settings (must match Inkwell's SERVICE_JWT_SECRET).
    """
    payload: dict = {"prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if schema:
        payload["schema"] = schema

    try:
        resp = requests.post(
            f"{_base_url()}/service/generate",
            json=payload,
            headers={"X-Service-Token": _mint_inkwell_service_token()},
            timeout=timeout_seconds or TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /service/generate timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /service/generate error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /service/generate returned {resp.status_code}")

    return resp.json()


def service_recognize_ocr_page(
    *,
    filename: str,
    content_type: str,
    file_base64: str,
    page_number: int,
    provider: str,
    engine: str | None = None,
) -> dict:
    """
    POST /service/recognition/ocr — OCR spike recognition adapter.

    The Core spike app owns state and curation; Inkwell owns recognition runtime
    and normalized OCR-like response shape.
    """
    payload = {
        "filename": filename,
        "content_type": content_type,
        "file_base64": file_base64,
        "page_number": page_number,
        "provider": provider,
    }
    if engine:
        payload["engine"] = engine
    try:
        resp = requests.post(
            f"{_base_url()}/service/recognition/ocr",
            json=payload,
            headers={"X-Service-Token": _mint_inkwell_service_token()},
            timeout=int(getattr(settings, "INKWELL_OCR_TIMEOUT_SECONDS", 240)),
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /service/recognition/ocr timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /service/recognition/ocr error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /service/recognition/ocr returned {resp.status_code}")

    return resp.json()


def synthesize(
    *,
    corpus: list,
    synthesis_goal: str,
    synthesis_mode: str = "handover",
    group_context: dict | None = None,
    output_template: str | None = None,
) -> dict:
    """
    POST /v1/synthesize → {synthesis, source_ids, synthesis_mode, coverage_score,
                            gaps_detected, local_preprocess_hash, model, ...}

    Governed by the synthesize_v1 schema contract (reference/prompts/synthesize.schema.yaml).
    Raises InkwellUnavailableError on any transport or HTTP error.
    """
    payload: dict = {
        "corpus": corpus,
        "synthesis_goal": synthesis_goal,
        "synthesis_mode": synthesis_mode,
    }
    if group_context:
        payload["group_context"] = group_context
    if output_template:
        payload["output_template"] = output_template

    try:
        resp = requests.post(
            f"{_base_url()}/v1/synthesize",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.exceptions.ReadTimeout:
        raise InkwellUnavailableError("Inkwell /v1/synthesize timed out")
    except requests.RequestException as e:
        raise InkwellUnavailableError(f"Inkwell unreachable: {e}")

    if resp.status_code != 200:
        logger.error("Inkwell /v1/synthesize error %s: %s", resp.status_code, resp.text[:500])
        raise InkwellUnavailableError(f"Inkwell /v1/synthesize returned {resp.status_code}")

    return resp.json()
