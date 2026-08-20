from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


RECIPE_SHAPE_ID = "food_service.recipe"
RECIPE_SHAPE_VERSION = "0.1.0"


BUILTIN_RECIPE_SCHEMA = {
    "type": "object",
    "required": ["shape_id", "shape_version", "title"],
    "additionalProperties": False,
    "properties": {
        "shape_id": {"type": "string"},
        "shape_version": {"type": "string"},
        "title": {"type": "string"},
        "yield": {"type": "string"},
        "timing": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prep": {"type": "string"},
                "cook": {"type": "string"},
                "total": {"type": "string"},
            },
        },
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item"],
                "additionalProperties": False,
                "properties": {
                    "quantity": {"type": "string"},
                    "unit": {"type": "string"},
                    "item": {"type": "string"},
                    "preparation": {"type": "string"},
                    "notes": {"type": "string"},
                    "original_text": {"type": "string"},
                    "uncertain": {"type": "boolean"},
                },
            },
        },
        "instructions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step_number", "text"],
                "additionalProperties": False,
                "properties": {
                    "step_number": {"type": "integer", "minimum": 1},
                    "text": {"type": "string"},
                    "uncertain": {"type": "boolean"},
                },
            },
        },
        "storage": {"type": "string"},
        "notes": {"type": "array", "items": {"type": "string"}},
        "source_fragments": {"type": "array", "items": {"type": "string"}},
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "reason"],
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string"},
                    "reason": {"type": "string"},
                    "source_text": {"type": "string"},
                },
            },
        },
    },
}

BUILTIN_RECIPE_EXTRACTION = """
Extract and organize the recipe that is already present. Do not improve,
modernize, complete, or invent the recipe. Preserve uncertainty. Ingredients
should preserve original text when quantity, unit, or item parsing is ambiguous.
Keep instructions in source order. Put storage guidance in storage and damaged
or conflicting readings in uncertain.
""".strip()

BUILTIN_RECIPE_TEMPLATE = """# {{title}}

Yield: {{yield}}

## Ingredients

{{ingredients}}

## Instructions

{{instructions}}

## Storage

{{storage}}

## Notes

{{notes}}

## Uncertain

{{uncertain}}
"""


@dataclass(frozen=True)
class ShapeDefinition:
    shape_id: str
    version: str
    name: str
    schema: dict
    markdown_template: str
    extraction_guidance: str
    validation_guidance: str
    source: str


def list_available_shapes() -> list[dict]:
    recipe = load_shape(RECIPE_SHAPE_ID)
    return [
        {
            "shape_id": recipe.shape_id,
            "shape_version": recipe.version,
            "name": recipe.name,
            "vertical": "food-service",
            "status": "draft",
            "source": recipe.source,
        }
    ]


def load_shape(shape_id: str) -> ShapeDefinition:
    if shape_id != RECIPE_SHAPE_ID:
        raise ValueError(f"Unsupported OCR spike shape: {shape_id}")
    from_files = _load_recipe_from_files()
    if from_files:
        return from_files
    return ShapeDefinition(
        shape_id=RECIPE_SHAPE_ID,
        version=RECIPE_SHAPE_VERSION,
        name="Recipe",
        schema=BUILTIN_RECIPE_SCHEMA,
        markdown_template=BUILTIN_RECIPE_TEMPLATE,
        extraction_guidance=BUILTIN_RECIPE_EXTRACTION,
        validation_guidance="Validate shape_id, shape_version, title, readable Markdown, and preserved uncertainty.",
        source="builtin",
    )


def generation_schema_for(shape: ShapeDefinition) -> dict:
    schema = _strip_json_schema_keywords(shape.schema)
    props = schema.setdefault("properties", {})
    props["shape_id"] = {"type": "string"}
    props["shape_version"] = {"type": "string"}
    schema["required"] = sorted(set(schema.get("required", []) + ["shape_id", "shape_version", "title"]))
    return schema


def render_recipe_markdown(data: dict) -> str:
    title = _text(data.get("title")) or "Untitled Recipe"
    lines = [f"# {title}", ""]
    if _text(data.get("yield")):
        lines.extend([f"Yield: {_text(data.get('yield'))}", ""])

    ingredients = data.get("ingredients") if isinstance(data.get("ingredients"), list) else []
    lines.extend(["## Ingredients", ""])
    if ingredients:
        for item in ingredients:
            if not isinstance(item, dict):
                continue
            bits = [
                _text(item.get("quantity")),
                _text(item.get("unit")),
                _text(item.get("item")),
                _text(item.get("preparation")),
            ]
            line = " ".join(bit for bit in bits if bit).strip()
            if _text(item.get("notes")):
                line = f"{line} ({_text(item.get('notes'))})".strip()
            if item.get("uncertain"):
                line = f"{line} [?]".strip()
            lines.append(f"- {line or _text(item.get('original_text')) or 'Unclear ingredient'}")
    else:
        lines.append("- ")

    instructions = data.get("instructions") if isinstance(data.get("instructions"), list) else []
    lines.extend(["", "## Instructions", ""])
    if instructions:
        for index, item in enumerate(instructions, start=1):
            if not isinstance(item, dict):
                continue
            step_number = item.get("step_number") if isinstance(item.get("step_number"), int) else index
            text = _text(item.get("text"))
            suffix = " [?]" if item.get("uncertain") else ""
            lines.append(f"{step_number}. {text}{suffix}")
    else:
        lines.append("1. ")

    storage = _text(data.get("storage"))
    if storage:
        lines.extend(["", "## Storage", "", storage])

    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    if notes:
        lines.extend(["", "## Notes", ""])
        for note in notes:
            lines.append(f"- {_text(note)}")

    uncertain = data.get("uncertain") if isinstance(data.get("uncertain"), list) else []
    if uncertain:
        lines.extend(["", "## Uncertain", ""])
        for item in uncertain:
            if isinstance(item, dict):
                field = _text(item.get("field")) or "unknown"
                reason = _text(item.get("reason"))
                source_text = _text(item.get("source_text"))
                lines.append(f"- {field}: {reason} {source_text}".strip())
            else:
                lines.append(f"- {_text(item)}")

    return "\n".join(lines).strip() + "\n"


def validate_recipe_shape(data: dict, shape: ShapeDefinition) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Model result was not a JSON object."]
    if data.get("shape_id") != shape.shape_id:
        errors.append(f"shape_id must be {shape.shape_id}.")
    if data.get("shape_version") != shape.version:
        errors.append(f"shape_version must be {shape.version}.")
    if not _text(data.get("title")):
        errors.append("title is required.")
    for index, ingredient in enumerate(data.get("ingredients") or [], start=1):
        if not isinstance(ingredient, dict):
            errors.append(f"ingredient {index} must be an object.")
        elif not _text(ingredient.get("item")):
            errors.append(f"ingredient {index} needs an item or should be moved to uncertain.")
    for index, instruction in enumerate(data.get("instructions") or [], start=1):
        if not isinstance(instruction, dict):
            errors.append(f"instruction {index} must be an object.")
        elif not _text(instruction.get("text")):
            errors.append(f"instruction {index} needs text or should be moved to uncertain.")
    return errors


def _load_recipe_from_files() -> ShapeDefinition | None:
    root = Path(getattr(settings, "OCR_SPIKE_SHAPE_LIBRARY_ROOT", "") or "")
    if not root:
        return None
    schema_path = root / "food-service" / "recipe.schema.json"
    template_path = root / "food-service" / "recipe.template.md"
    extraction_path = root / "food-service" / "recipe.extraction.md"
    validation_path = root / "food-service" / "recipe.validation.md"
    if not schema_path.exists():
        return None
    try:
        schema = json.loads(schema_path.read_text())
        return ShapeDefinition(
            shape_id=RECIPE_SHAPE_ID,
            version=RECIPE_SHAPE_VERSION,
            name="Recipe",
            schema=schema,
            markdown_template=template_path.read_text() if template_path.exists() else BUILTIN_RECIPE_TEMPLATE,
            extraction_guidance=extraction_path.read_text() if extraction_path.exists() else BUILTIN_RECIPE_EXTRACTION,
            validation_guidance=validation_path.read_text() if validation_path.exists() else "",
            source=str(root),
        )
    except Exception:
        return None


def _strip_json_schema_keywords(value):
    if isinstance(value, dict):
        next_value = {}
        for key, item in value.items():
            if key in {"$schema", "$id", "title", "const", "description"}:
                continue
            next_value[key] = _strip_json_schema_keywords(item)
        return next_value
    if isinstance(value, list):
        return [_strip_json_schema_keywords(item) for item in value]
    return value


def _text(value) -> str:
    return str(value or "").strip()
