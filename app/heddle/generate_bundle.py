"""Generate/check the selected Contour bundle, never from consumer schemas.

Run: python -m heddle.generate_bundle --contour-root /path/to/puddlejump/reference/contour
Add --check for CI drift verification. Production only reads the shipped JSON.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

from .bundle import BUNDLE_PATH, digest

SHELVES = ("writing", "shuttle")
STRATEGY = "writing.fiction_note_reading"


def generate(root, source_commit):
    root = Path(root).resolve()
    files, schemas = {}, {}

    def add(path):
        path = path.resolve()
        relative = path.relative_to(root).as_posix()
        text = path.read_bytes().decode("utf-8")
        files[relative] = {"sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text}
        return relative

    manifest = yaml.safe_load((root / "manifest.yaml").read_text())
    # Include only selected manifest entries; unrelated canon edits do not cause drift.
    selected = [v for v in manifest["verticals"] if v["id"] in SHELVES]
    if {v["id"] for v in selected} != set(SHELVES):
        raise ValueError("Selected Contour shelf missing")
    for shelf in selected:
        add(root / shelf["id"] / "README.md") if (root / shelf["id"] / "README.md").exists() else None
        for shape in shelf["shapes"]:
            for field in ("shape_file", "schema_file", "markdown_template", "extraction_guidance", "validation_guidance"):
                add(root / shape[field])
            schema = json.loads((root / shape["schema_file"]).read_text())
            Draft7Validator.check_schema(schema)
            if (schema["properties"]["shape_id"]["const"] != shape["id"] or
                    schema["properties"]["shape_version"]["const"] != str(shape["version"])):
                raise ValueError("Contour manifest/schema identity mismatch")
            schemas[f'{shape["id"]}@{shape["version"]}'] = shape["schema_file"]
        for path in sorted((root / shelf["id"] / "versions").glob("*.schema.json")):
            schema = json.loads(path.read_text())
            Draft7Validator.check_schema(schema)
            key = f'{schema["properties"]["shape_id"]["const"]}@{schema["properties"]["shape_version"]["const"]}'
            relative = add(path)
            if key in schemas and files[schemas[key]]["text"] != files[relative]["text"]:
                raise ValueError(f"Conflicting retained schema: {key}")
            schemas.setdefault(key, relative)
    strategies = [e for group in manifest["strategies"] for e in group.get("entries", []) if e["id"] == STRATEGY]
    if len(strategies) != 1:
        raise ValueError("Folio Strategy missing or ambiguous")
    strategy = strategies[0]
    for field in ("contract_file", "prose_file"):
        prefix = "puddlejump/reference/contour/"
        if not strategy[field].startswith(prefix):
            raise ValueError("Unexpected Strategy source path")
        add(root / strategy[field][len(prefix):])
    return {"format_version": 1, "source_commit": source_commit,
            "library_version": str(manifest["library_version"]),
            "selection": {"verticals": selected, "strategies": strategies},
            "schemas": schemas, "files": dict(sorted(files.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contour-root", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=BUNDLE_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.contour_root.resolve()
    previous = json.loads(args.output.read_text()) if args.output.exists() else None
    existing = previous if args.check else None
    if args.check and existing is None:
        raise SystemExit("Contour bundle missing: generate it first")
    # Check content against the checkout while retaining the original provenance
    # commit; unrelated Puddlejump commits must not continually rewrite the bundle.
    commit = existing["source_commit"] if existing else subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if not args.check:
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--", "."], text=True)
        if dirty.strip():
            raise SystemExit("Commit canonical Contour edits before generating a release bundle")
    result = generate(root, commit)
    if previous and set(previous["schemas"]) - set(result["schemas"]):
        raise SystemExit("Retain every previously bundled Shape version in canonical Contour")
    result["digest"] = digest(result)
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        if args.output.read_text() != rendered:
            raise SystemExit("Contour bundle drift: regenerate from accepted canon")
        print("Contour bundle matches selected canonical dependencies")
    else:
        args.output.write_text(rendered)
        print(f"Generated {args.output}: {result['digest']}")


if __name__ == "__main__":
    main()
