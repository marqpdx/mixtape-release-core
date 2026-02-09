# stackroom/services/llm_provider.py

"""
Pluggable LLM Provider

Provides a simple interface for text generation backed by configurable
LLM backends. Default is Ollama (local inference, no API key needed).

Reads configuration from Django settings:
    LLM_BACKEND  — "ollama" (default), "openai", or "anthropic"
    LLM_BASE_URL — Ollama: "http://localhost:11434", OpenAI-compat: any URL
    LLM_MODEL    — Model name, e.g. "llama3.1:8b"
    LLM_API_KEY  — API key (only needed for cloud backends)

Used by Puddlejump utilities (Phases 5+):
    - Suggest Summaries (8B sufficient)
    - Restructure / Consolidate (8B, pipelined steps)
    - Find Contradictions (aspirational, benefits from 70B+)
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMNotAvailableError(Exception):
    """Raised when the configured LLM backend is not reachable."""
    pass


def is_available() -> bool:
    """Check whether the configured LLM backend is reachable."""
    backend = getattr(settings, "LLM_BACKEND", "ollama")

    if backend == "ollama":
        return _check_ollama()
    elif backend in ("openai", "anthropic"):
        api_key = getattr(settings, "LLM_API_KEY", None)
        return bool(api_key)
    return False


def generate(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Generate text using the configured LLM backend.

    Args:
        prompt: The user/input prompt.
        system_prompt: Optional system prompt for context.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).

    Returns:
        Generated text string.

    Raises:
        LLMNotAvailableError: If the backend is not reachable or misconfigured.
    """
    backend = getattr(settings, "LLM_BACKEND", "ollama")

    if backend == "ollama":
        return _generate_ollama(prompt, system_prompt, max_tokens, temperature)
    elif backend == "openai":
        return _generate_openai(prompt, system_prompt, max_tokens, temperature)
    elif backend == "anthropic":
        return _generate_anthropic(prompt, system_prompt, max_tokens, temperature)
    else:
        raise LLMNotAvailableError(f"Unknown LLM backend: {backend}")


# ============================================================================
# OLLAMA (default — local inference)
# ============================================================================

def _check_ollama() -> bool:
    """Check if Ollama is running and has the configured model."""
    base_url = getattr(settings, "LLM_BASE_URL", "http://localhost:11434")
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_name = getattr(settings, "LLM_MODEL", "llama3.1:8b")
            # Check if the model is available (match by name prefix)
            model_base = model_name.split(":")[0]
            return any(model_base in m.get("name", "") for m in models)
        return False
    except (requests.ConnectionError, requests.Timeout):
        return False


def _generate_ollama(
    prompt: str,
    system_prompt: Optional[str],
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = getattr(settings, "LLM_BASE_URL", "http://localhost:11434")
    model = getattr(settings, "LLM_MODEL", "llama3.1:8b")

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except requests.ConnectionError:
        raise LLMNotAvailableError(
            f"Cannot connect to Ollama at {base_url}. "
            "Is Ollama running? Start with: ollama serve"
        )
    except requests.Timeout:
        raise LLMNotAvailableError("Ollama request timed out (120s)")
    except requests.HTTPError as e:
        raise LLMNotAvailableError(f"Ollama HTTP error: {e}")


# ============================================================================
# OPENAI-COMPATIBLE (optional — any OpenAI-compatible API)
# ============================================================================

def _generate_openai(
    prompt: str,
    system_prompt: Optional[str],
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = getattr(settings, "LLM_BASE_URL", "https://api.openai.com/v1")
    api_key = getattr(settings, "LLM_API_KEY", None)
    model = getattr(settings, "LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        raise LLMNotAvailableError("LLM_API_KEY is required for OpenAI backend")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.ConnectionError:
        raise LLMNotAvailableError(f"Cannot connect to OpenAI API at {base_url}")
    except (KeyError, IndexError):
        raise LLMNotAvailableError("Unexpected response format from OpenAI API")
    except requests.HTTPError as e:
        raise LLMNotAvailableError(f"OpenAI API error: {e}")


# ============================================================================
# ANTHROPIC (optional — Claude API, cloud only)
# ============================================================================

def _generate_anthropic(
    prompt: str,
    system_prompt: Optional[str],
    max_tokens: int,
    temperature: float,
) -> str:
    api_key = getattr(settings, "LLM_API_KEY", None)
    model = getattr(settings, "LLM_MODEL", "claude-sonnet-4-5-20250929")

    if not api_key:
        raise LLMNotAvailableError("LLM_API_KEY is required for Anthropic backend")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        payload["system"] = system_prompt

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        content_blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
    except requests.ConnectionError:
        raise LLMNotAvailableError("Cannot connect to Anthropic API")
    except (KeyError, IndexError):
        raise LLMNotAvailableError("Unexpected response format from Anthropic API")
    except requests.HTTPError as e:
        raise LLMNotAvailableError(f"Anthropic API error: {e}")
