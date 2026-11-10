"""Release-local Contour dependency bundle. Contour alone owns its contents."""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator, ValidationError

BUNDLE_PATH = Path(__file__).with_name("contour_bundle.json")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=1)
def _load():
    bundle = json.loads(BUNDLE_PATH.read_text())
    if bundle.get("digest") != digest({k: v for k, v in bundle.items() if k != "digest"}):
        raise ValueError("Contour bundle digest mismatch")
    for path, entry in bundle["files"].items():
        if hashlib.sha256(entry["text"].encode()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Contour file digest mismatch: {path}")
    return bundle


def bundle_identity():
    bundle = _load()
    return {key: bundle[key] for key in ("digest", "source_commit", "library_version")}


def shape_schema(shape_id, version):
    """Bundle first. Provisional Shape lookup is a future extension, not a fallback."""
    path = _load()["schemas"].get(f"{shape_id}@{version}")
    if path is None:
        raise ValidationError(f"Unknown Shape version: {shape_id}@{version}")
    return copy.deepcopy(json.loads(_load()["files"][path]["text"]))


def validate_sighting(sighting):
    if not isinstance(sighting, dict):
        raise ValidationError("Sighting must be an object")
    schema = shape_schema(sighting.get("shape_id"), sighting.get("shape_version"))
    Draft7Validator(schema).validate(sighting)
    return sighting


def validate_shaped_payload(payload):
    """
    Generic Shape validation, for any bundled Shape -- not just sightings.
    The payload names its own shape_id/shape_version (required fields on
    every Shape); this looks up and applies that Shape's schema.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be an object")
    schema = shape_schema(payload.get("shape_id"), payload.get("shape_version"))
    Draft7Validator(schema).validate(payload)
    return payload
