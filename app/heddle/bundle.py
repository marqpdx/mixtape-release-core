"""Release-local Contour dependency bundle. Contour alone owns its contents."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from jsonschema import Draft7Validator, FormatChecker, ValidationError
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT7

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


def _no_external_resource(uri):
    raise NoSuchResource(ref=uri)


def _schema_resources(bundle):
    resources = {}
    for path, entry in bundle["files"].items():
        if not path.endswith(".schema.json"):
            continue
        schema = json.loads(entry["text"])
        Draft7Validator.check_schema(schema)
        resource = Resource.from_contents(schema, default_specification=DRAFT7)
        for identifier in (path, schema.get("$id")):
            if identifier is None:
                continue
            if identifier in resources and resources[identifier].contents != schema:
                raise ValueError(f"Conflicting bundled schema identifier: {identifier}")
            resources[identifier] = resource
    return resources


def schema_registry(bundle=None):
    """Only pinned resources may resolve, even if a missing ref is an HTTP URL."""
    source = _load() if bundle is None else bundle
    return Registry(retrieve=_no_external_resource).with_resources(_schema_resources(source).items()).crawl()


def check_schema_references(bundle):
    """Preflight every ref, including refs in branches no instance has used yet."""
    registry = schema_registry(bundle)

    def check(resource, resolver):
        if isinstance(resource.contents, dict) and "$ref" in resource.contents:
            try:
                resolver.lookup(resource.contents["$ref"])
            except Unresolvable as exc:
                raise ValueError("Schema reference is absent from the pinned bundle") from exc
        for child in resource.subresources():
            check(child, resolver.in_subresource(child))

    for resource in _schema_resources(bundle).values():
        check(resource, registry.resolver_with_root(resource))


_FORMATS = FormatChecker()


@_FORMATS.checks("uuid", raises=ValueError)
def _uuid_format(value):
    if not isinstance(value, str):
        return True  # Type is checked by the schema.
    return str(UUID(value)) == value.lower()


@_FORMATS.checks("date-time", raises=ValueError)
def _date_time_format(value):
    # Core emits ordinary UTC instants; do not silently skip this format when
    # jsonschema's optional date-time dependency is absent from the environment.
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})", value):
        return False
    return datetime.fromisoformat(value.upper().replace("Z", "+00:00")).tzinfo is not None


def schema_validator(schema, *, bundle=None):
    return Draft7Validator(schema, registry=schema_registry(bundle), format_checker=_FORMATS)


def validate_sighting(sighting):
    if not isinstance(sighting, dict):
        raise ValidationError("Sighting must be an object")
    schema = shape_schema(sighting.get("shape_id"), sighting.get("shape_version"))
    schema_validator(schema).validate(sighting)
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
    schema_validator(schema).validate(payload)
    return payload
