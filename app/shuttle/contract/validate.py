# shuttle/contract/validate.py
#
# Schema validation for the Shuttle packet contract (ADR-0058, SH-7a).
# Shared by the contract's own fixture tests and by the Governed Verb
# Envelope service (SH-7b), so both check against the same four schemas.
import json
from pathlib import Path

from jsonschema import Draft7Validator, ValidationError

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


def _load_schema(name):
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


_WEAVE_IN_SCHEMA = _load_schema("weave_in.schema.json")
_PACKET_OUT_SCHEMA = _load_schema("packet_out.schema.json")
_CONFIRM_IN_SCHEMA = _load_schema("confirm_in.schema.json")
_RESULT_OUT_SCHEMA = _load_schema("result_out.schema.json")


def _validate(instance, schema):
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        raise ValidationError(
            "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        )


def validate_weave_in(instance):
    _validate(instance, _WEAVE_IN_SCHEMA)


def validate_packet_out(instance):
    _validate(instance, _PACKET_OUT_SCHEMA)


def validate_confirm_in(instance):
    _validate(instance, _CONFIRM_IN_SCHEMA)


def validate_result_out(instance):
    _validate(instance, _RESULT_OUT_SCHEMA)
