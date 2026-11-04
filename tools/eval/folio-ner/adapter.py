"""M1 offline JSONL recognition contract. Standard library; no model or Django."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from recognition import Request, cue_matcher

VERSION = "0.1.0-draft"
SHAPES = ("writing.character", "writing.setting", "writing.scene")
PRODUCER_KEYS = {"kind", "id", "version", "model_revision"}
REQUEST_KEYS = {"contract_version", "source", "source_digest", "context", "context_digest", "step_id", "step_version"}
RESPONSE_KEYS = {"contract_version", "source_ref", "source_revision", "source_digest", "context_revision",
                 "context_digest", "bundle_digest", "step_id", "step_version", "candidates"}
CANDIDATE_KEYS = {"candidate_id", "candidate_kind", "type", "source_locator", "score", "negated", "ambiguous", "uncertain", "producer"}


def digest(value):
    # Byte-for-byte equivalent to Heddle's canonical identity hashing; no runtime import.
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"Invalid {label} fields")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def load_context(bundle_path):
    bundle = json.loads(Path(bundle_path).read_text())
    if bundle.get("digest") != digest({k: v for k, v in bundle.items() if k != "digest"}):
        raise ValueError("Contour bundle digest mismatch")
    for relative, entry in bundle["files"].items():
        if text_hash(entry["text"]) != entry["sha256"]:
            raise ValueError(f"Contour dependency digest mismatch: {relative}")
    strategies = bundle["selection"]["strategies"]
    if not any(s["id"] == "writing.fiction_note_reading" and s["version"] == "0.1.0" for s in strategies):
        raise ValueError("Pinned Fiction Strategy missing")
    vocabulary = []
    for shape_id in SHAPES:
        filename = shape_id.split(".")[1]
        path = f"writing/{filename}.shape.yaml"
        entry = bundle["files"][path]
        # Narrow reader for the current Contour scalar cue-list representation,
        # not a general YAML parser. Fail if this representation grows more complex.
        match = re.search(r"^synonyms:\n((?:- [^\n]+\n)+)", entry["text"], re.M)
        if not match:
            raise ValueError(f"Unsupported Contour cue-list representation: {path}")
        terms = [line[2:] for line in match.group(1).splitlines()]
        if any(not re.fullmatch(r"[\w -]+", term) for term in terms):
            raise ValueError("Complex YAML cue scalar requires an approved parser")
        schema = json.loads(bundle["files"][bundle["schemas"][f"{shape_id}@0.1.0"]]["text"])
        if schema["properties"]["shape_id"]["const"] != shape_id:
            raise ValueError("Shape identity mismatch")
        vocabulary.append({"shape_id": shape_id, "shape_version": "0.1.0", "cues": terms,
                           "source_path": path, "source_sha256": entry["sha256"]})
    return {"revision": 0, "work_type": "fiction", "title": "Synthetic M1 evaluation",
            "strategy_id": "writing.fiction_note_reading", "strategy_version": "0.1.0",
            "contour": {"library_id": "crossroads.shape_library", "library_version": bundle["library_version"],
                        "bundle_digest": bundle["digest"], "source_commit": bundle["source_commit"]},
            "vocabulary": vocabulary, "confirmed_entity_aliases": [], "project_markers": [], "field_labels": []}


def make_request(source, context):
    request = {"contract_version": VERSION, "source": source, "source_digest": digest([source]),
               "context": context, "context_digest": digest(context),
               "step_id": "recognition_eval", "step_version": "0.1.0"}
    validate_request(request)
    return request


def validate_request(request):
    keys(request, REQUEST_KEYS, "request")
    source, context = request["source"], request["context"]
    keys(source, {"source_ref", "source_revision", "text"}, "source")
    if (request["contract_version"] != VERSION or not nonempty(source["source_ref"]) or
            not isinstance(source["text"], str) or not source["text"] or
            type(source["source_revision"]) is not int or source["source_revision"] < 0 or
            not isinstance(context, dict) or type(context.get("revision")) is not int or context["revision"] < 0 or
            not nonempty(request["step_id"]) or not nonempty(request["step_version"])):
        raise ValueError("Invalid request identity")
    if request["source_digest"] != digest([source]) or request["context_digest"] != digest(context):
        raise ValueError("Source/context digest mismatch")
    contour = context.get("contour", {})
    if not isinstance(contour, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(contour.get("bundle_digest", ""))):
        raise ValueError("Missing pinned Contour identity")
    if not all(nonempty(contour.get(k)) for k in ("library_id", "library_version", "source_commit")):
        raise ValueError("Incomplete Contour identity")
    vocabulary = context.get("vocabulary")
    if not isinstance(vocabulary, list) or len(vocabulary) != len(SHAPES):
        raise ValueError("Whole initial Writing vocabulary required")
    if {row.get("shape_id") for row in vocabulary} != set(SHAPES):
        raise ValueError("Unexpected Writing vocabulary")
    for row in vocabulary:
        if (row.get("shape_version") != "0.1.0" or not isinstance(row.get("cues"), list) or
                not row["cues"] or not all(nonempty(t) for t in row["cues"]) or
                not nonempty(row.get("source_path")) or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("source_sha256", "")))):
            raise ValueError("Invalid pinned vocabulary entry")


def response_identity(request):
    return {"contract_version": VERSION, "source_ref": request["source"]["source_ref"],
            "source_revision": request["source"]["source_revision"], "source_digest": request["source_digest"],
            "context_revision": request["context"]["revision"], "context_digest": request["context_digest"],
            "bundle_digest": request["context"]["contour"]["bundle_digest"],
            "step_id": request["step_id"], "step_version": request["step_version"]}


def validate_response(request, response):
    validate_request(request)
    keys(response, RESPONSE_KEYS, "response")
    if any(type(response[k]) is not type(value) or response[k] != value for k, value in response_identity(request).items()):
        raise ValueError("Stale or incompatible response identity")
    if not isinstance(response["candidates"], list):
        raise ValueError("Candidates must be an array")
    seen = set()
    source = request["source"]
    for candidate in response["candidates"]:
        keys(candidate, CANDIDATE_KEYS, "candidate")
        cid = candidate["candidate_id"]
        if not nonempty(cid) or cid in seen:
            raise ValueError("Missing/duplicate candidate id")
        seen.add(cid)
        if candidate["candidate_kind"] not in {"cue", "mention"} or candidate["type"] not in SHAPES:
            raise ValueError("Invalid recognition candidate type")
        loc = candidate["source_locator"]
        keys(loc, {"source_ref", "source_revision", "start", "end", "quote"}, "source locator")
        start, end = loc["start"], loc["end"]
        if (loc["source_ref"] != source["source_ref"] or type(loc["source_revision"]) is not int or loc["source_revision"] != source["source_revision"] or
                type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]) or
                source["text"][start:end] != loc["quote"]):
            raise ValueError("Invalid/nonverbatim Unicode code-point span")
        if type(candidate["negated"]) is not bool or type(candidate["ambiguous"]) is not bool:
            raise ValueError("Candidate qualifiers must be booleans")
        if not isinstance(candidate["uncertain"], list) or not all(nonempty(x) for x in candidate["uncertain"]):
            raise ValueError("Invalid candidate uncertainty")
        score = candidate["score"]
        if score is not None and (type(score) not in {float, int} or not 0 <= score <= 1):
            raise ValueError("Score must be null or a finite uncalibrated value in [0,1]")
        producer = candidate["producer"]
        keys(producer, PRODUCER_KEYS, "producer")
        if (producer["kind"] not in {"rule", "model", "prompt"} or
                not nonempty(producer["id"]) or not nonempty(producer["version"])):
            raise ValueError("Invalid producer provenance")
        if producer["kind"] == "rule" and (producer["model_revision"] is not None or score is not None):
            raise ValueError("A deterministic rule has no model revision or model score")
        if producer["kind"] != "rule" and not nonempty(producer["model_revision"]):
            raise ValueError("Model/prompt output requires a pinned model revision")


def recognize(request):
    validate_request(request)
    source, context = request["source"], request["context"]
    aliases = tuple((row["shape_id"], cue) for row in context["vocabulary"] for cue in row["cues"])
    legacy = cue_matcher(Request(source["text"], source["source_revision"], str(context["revision"]), aliases))
    candidates = []
    for index, cue in enumerate(legacy["cues"]):
        candidates.append({"candidate_id": f"cue-{index + 1}", "candidate_kind": "cue", "type": cue["shape_id"],
            "source_locator": {"source_ref": source["source_ref"], "source_revision": source["source_revision"], **cue["span"]},
            "score": None, "negated": cue["negated"], "ambiguous": cue["ambiguous"], "uncertain": [],
            "producer": {"kind": "rule", "id": "mobile-cue-baseline", "version": "d0ee754e", "model_revision": None}})
    response = {**response_identity(request), "candidates": candidates}
    validate_response(request, response)
    return response
