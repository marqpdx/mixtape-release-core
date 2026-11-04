"""Offline recognition seam proposal. No model, network or production imports."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol, TypedDict

VERSION = "0.1-proposal"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Request:
    text: str
    source_revision: int
    context_version: str
    # Supplied by a versioned Contour/context loader, not an independent vocabulary.
    aliases: tuple[tuple[str, str], ...]  # (Shape id, cue)

    @property
    def context_digest(self) -> str:
        return fingerprint(json.dumps({"version": self.context_version, "aliases": self.aliases},
                                     ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class Span(TypedDict):
    start: int
    end: int
    quote: str


class Cue(TypedDict):
    shape_id: str
    span: Span
    negated: bool
    ambiguous: bool


class Mention(TypedDict):
    kind: str
    span: Span
    uncertain: list[str]


class RecognitionResult(TypedDict):
    contract_version: str
    source_digest: str
    source_revision: int
    context_version: str
    context_digest: str
    backend: str
    model_revision: str | None
    cues: list[Cue]
    mentions: list[Mention]


class Adapter(Protocol):
    """One initialized adapter per process; loading models per note is forbidden."""
    def recognize(self, request: Request) -> RecognitionResult: ...


def cue_matcher(request: Request) -> RecognitionResult:
    """Conservative cue spotting only, not Entity NER or Shape confirmation.

    Negated/ordinary-language cues remain inspectable candidates with qualifiers;
    they never become accepted Shapes. No names or narrative are inferred here.
    """
    cues = []
    seen = set()
    for shape_id, alias in request.aliases:
        if not alias.strip():
            raise ValueError("Empty cue")
        for match in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", request.text, re.IGNORECASE):
            identity = (shape_id, match.start(), match.end())
            if identity in seen:
                continue
            seen.add(identity)
            prefix = request.text[max(0, match.start() - 32):match.start()]
            suffix = request.text[match.end():match.end() + 40]
            negated = bool(re.search(r"\b(?:not|isn't|isn’t|no)(?:\s+(?:a|an|the))?\s*$", prefix, re.I))
            ordinary = bool(re.match(r"\s+of\s+(?:the\s+)?(?:file|folder|document)\b", suffix, re.I))
            cues.append({"shape_id": shape_id,
                         "span": {"start": match.start(), "end": match.end(), "quote": match.group()},
                         "negated": negated, "ambiguous": ordinary})
    result = {"contract_version": VERSION, "source_digest": fingerprint(request.text),
              "source_revision": request.source_revision, "context_version": request.context_version,
              "context_digest": request.context_digest,
              "backend": "deterministic-cues", "model_revision": None,
              "cues": sorted(cues, key=lambda cue: (cue["span"]["start"], cue["shape_id"])),
              "mentions": []}
    validate_result(request, result)
    return result


def validate_result(request: Request, result: dict) -> None:
    """Adapter boundary checks; source/context mismatches and bad spans fail closed."""
    expected = {"contract_version": VERSION, "source_digest": fingerprint(request.text),
                "source_revision": request.source_revision, "context_version": request.context_version,
                "context_digest": request.context_digest}
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("Stale source/context or incompatible adapter contract")
    for collection in ("cues", "mentions"):
        if not isinstance(result.get(collection), list):
            raise ValueError("Missing candidate collection")
        for candidate in result[collection]:
            span = candidate["span"]
            start, end = span["start"], span["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(request.text):
                raise ValueError("Invalid Unicode code-point span")
            if request.text[start:end] != span["quote"]:
                raise ValueError("Candidate is not verbatim")


def exact_span_scores(predicted: list[dict], gold: list[dict]) -> dict:
    """Exact label+code-point-span micro scoring; duplicates count as false positives.

    Inputs use {label, start, end}; supply source_ref when pooling multiple notes.
    Labels for NER and cues are evaluated separately.
    No fuzzy overlap, confidence calibration or model-quality claim is implied.
    """
    def counts(rows):
        return Counter((row.get("source_ref", ""), row["label"], row["start"], row["end"]) for row in rows)
    actual, expected = counts(predicted), counts(gold)
    tp = sum((actual & expected).values())
    fp, fn = sum(actual.values()) - tp, sum(expected.values()) - tp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
