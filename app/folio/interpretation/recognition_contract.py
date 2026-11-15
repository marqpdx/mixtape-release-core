"""Accepted SE-2 wire contract. JSON values cross an untyped schema boundary.

The schemas/profile are exact copies of Core c1ac2b15, not Contour Shapes.
max_source_chars is the aggregate code-point budget, including corrections.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).with_name("contracts")
PROFILE: dict[str, Any] = json.loads((ROOT / "profile.json").read_text())
PROTOCOL = "selene.recognition/0.1.0"


class RecognitionError(ValueError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code = code
        self.status = status


def require(condition: bool, code: str, status: int = 422) -> None:
    if not condition:
        raise RecognitionError(code, status)


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RecognitionError("invalid_json") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_DIGEST = digest(PROFILE)
PRODUCER = {"kind": "model", "id": PROFILE["model_id"], "version": PROFILE["library_version"],
            "model_revision": PROFILE["model_revision"], "profile_digest": PROFILE_DIGEST}


def schema(kind: str, value: Any) -> None:
    # Lazy import permits exact-model adapter tests in the existing model-only
    # environment. The serving dependency closure includes jsonschema.
    from jsonschema import Draft7Validator, FormatChecker, ValidationError  # type: ignore[import-untyped]
    checker = FormatChecker()

    def uuid_format(item: Any) -> bool:
        return isinstance(item, str) and str(UUID(item)) == item

    checker.checks("uuid", raises=(ValueError, TypeError, AttributeError))(uuid_format)

    try:
        Draft7Validator(json.loads((ROOT / (kind + ".schema.json")).read_text()),
                        format_checker=checker).validate(value)
    except (ValidationError, RecursionError):
        raise RecognitionError("invalid_" + kind) from None


def validate_request(request: dict[str, Any]) -> None:
    require(len(canonical(request)) <= PROFILE["max_request_bytes"], "request_too_large", 413)
    require(request.get("local_only") is True, "policy_forbids_cloud", 403)
    sources = request.get("sources")
    if isinstance(sources, list):
        require(len(sources) <= PROFILE["max_sources"], "too_many_sources", 413)
        if all(isinstance(s, dict) and isinstance(s.get("text"), str) for s in sources):
            require(sum(len(s["text"]) for s in sources) <= PROFILE["max_source_chars"],
                    "source_too_long", 413)
    schema("request", request)
    binding, sources, context = request["binding"], request["sources"], request["context"]
    require(request["profile_digest"] == PROFILE_DIGEST, "profile_conflict")
    require(all(type(binding[k]) is int for k in ("revision", "context_revision")), "invalid_revision")
    require(type(context["revision"]) is int, "invalid_revision")
    require(binding["source_digest"] == digest(sources), "source_conflict")
    require(binding["context_digest"] == digest(context), "context_conflict")
    require(binding["context_revision"] == context["revision"], "context_conflict")
    require(binding["bundle_digest"] == context["bundle"]["digest"], "bundle_conflict")
    require(all(type(s["source_revision"]) is int and s["source_revision"] <= binding["revision"]
                and bool(s["text"].strip()) for s in sources), "invalid_source")
    require(len({(s["source_ref"], s["source_revision"]) for s in sources}) == len(sources), "duplicate_source")
    require(len(canonical(context).decode("utf-8")) <= PROFILE["max_context_chars"], "context_too_large", 413)


def validate_response(request: dict[str, Any], response: dict[str, Any]) -> None:
    validate_request(request)
    require(len(canonical(response)) <= PROFILE["max_response_bytes"], "response_too_large", 413)
    schema("response", response)
    require(all(type(response["binding"][key]) is int for key in ("revision", "context_revision")),
            "invalid_revision")
    require(response["binding"] == request["binding"], "binding_conflict")
    require(response["profile_digest"] == request["profile_digest"], "profile_conflict")
    require(response["request_fingerprint"] == digest(request), "request_conflict")
    sources = {(s["source_ref"], s["source_revision"]): s["text"] for s in request["sources"]}
    seen: set[str] = set()
    for candidate in response["candidates"]:
        locator = candidate["source_locator"]
        text = sources.get((locator["source_ref"], locator["source_revision"]))
        start, end = locator["start"], locator["end"]
        require(all(type(locator[k]) is int for k in ("start", "end", "source_revision")), "invalid_span")
        require(text is not None and 0 <= start < end <= len(text) and text[start:end] == locator["quote"],
                "invalid_span")
        score = candidate["score"]
        require(type(score) in (int, float) and math.isfinite(score), "invalid_score")
        expected = "m-" + digest({"execution_action_run_id": request["binding"]["execution_action_run_id"],
                                  "type": candidate["type"], "source_locator": locator})[:32]
        require(candidate["candidate_id"] == expected, "candidate_identity_conflict")
        require(expected not in seen, "duplicate_candidate")
        require(candidate["producer"] == PRODUCER, "producer_conflict")
        seen.add(expected)


def parse_request(body: bytes) -> dict[str, Any]:
    require(len(body) <= PROFILE["max_request_bytes"], "request_too_large", 413)

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise RecognitionError("invalid_json") from None
    require(isinstance(value, dict), "invalid_request")
    validate_request(value)
    return value  # type: ignore[no-any-return]
