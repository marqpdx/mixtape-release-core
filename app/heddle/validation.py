"""Shared checks; surface callbacks retain Shape meaning and typed reference rules."""
from jsonschema import ValidationError

from .bundle import validate_sighting


def validate_result(reading, result, sources):
    if reading.steps:
        sightings = result.get("sightings", [])
        by_id = {}
        for sighting in sightings:
            validate_sighting(sighting)
            sid = sighting["sighting_id"]
            if sid in by_id:
                raise ValidationError("Duplicate Sighting id")
            by_id[sid] = sighting
        source_map = {(s["source_ref"], s["source_revision"]): s["text"] for s in sources}

        def spans(value):
            if isinstance(value, dict):
                if {"source_ref", "source_revision", "start", "end", "quote"} <= value.keys():
                    text = source_map.get((value["source_ref"], value["source_revision"]))
                    start, end = value["start"], value["end"]
                    if (text is None or type(start) is not int or type(end) is not int or
                            not 0 <= start < end <= len(text) or text[start:end] != value["quote"]):
                        raise ValidationError("Invalid or nonverbatim source span")
                for item in value.values():
                    spans(item)
            elif isinstance(value, list):
                for item in value:
                    spans(item)
        spans(result)
        for sighting in sightings:
            for field, allowed_shapes in reading.reference_fields:
                for sid in sighting.get(field, []):
                    if sid not in by_id or (allowed_shapes and by_id[sid]["shape_id"] not in allowed_shapes):
                        raise ValidationError(f"Invalid Sighting reference in {field}: {sid}")
        for question in result.get("questions", []):
            for sid in question.get("sighting_ids", []):
                if sid not in by_id:
                    raise ValidationError(f"Invalid question Sighting reference: {sid}")
    return reading.validate_findings(result, sources)
