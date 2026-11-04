"""Compile proposed quote annotations to exact immutable code-point spans."""
import json
from pathlib import Path

from adapter import digest, make_request, text_hash

SPLITS = {"tuning", "contrast", "paraphrase", "holdout"}


def locate(text, annotation):
    quote = annotation["quote"]
    if not isinstance(quote, str) or not quote:
        raise ValueError("Annotation quote must be nonempty")
    positions, start = [], 0
    while True:
        found = text.find(quote, start)
        if found < 0:
            break
        positions.append(found)
        start = found + 1
    if not positions:
        raise ValueError(f"Annotation quote absent: {quote!r}")
    occurrence = annotation.get("occurrence")
    if occurrence is None:
        if len(positions) != 1:
            raise ValueError(f"Repeated quote needs an explicit occurrence: {quote!r}")
        occurrence = 1
    if type(occurrence) is not int or not 1 <= occurrence <= len(positions):
        raise ValueError("Invalid annotation occurrence")
    offset = positions[occurrence - 1]
    return {"start": offset, "end": offset + len(quote), "quote": quote}


def compile_cases(rows, context):
    seen, seen_text = set(), set()
    if not 12 <= len(rows) <= 21:
        raise ValueError("M1 requires 12–21 cases (CTO-expanded set, 2026-11-03)")
    compiled = []
    for row in rows:
        if row["id"] in seen or row["split"] not in SPLITS:
            raise ValueError("Duplicate case id or invalid split")
        seen.add(row["id"])
        text = row["text"]
        if text_hash(text) in seen_text:
            raise ValueError("Duplicate text across evaluation cases")
        seen_text.add(text_hash(text))
        source = {"source_ref": f"synthetic:{row['id']}", "source_revision": 0, "text": text}
        annotations = {}
        for kind in ("cues", "mentions", "traps", "ambiguities"):
            annotations[kind] = [{**{k: v for k, v in item.items() if k not in {"quote", "occurrence"}},
                                  **locate(text, item)} for item in row[kind]]
        if any(type(a.get("optional", False)) is not bool for a in annotations["mentions"]):
            raise ValueError("Optional gold flag must be boolean")
        annotations["shape_judgements"] = [{"shape_id": item["shape_id"], "judgement": item["judgement"],
            "evidence": [locate(text, evidence) for evidence in item["evidence"]]} for item in row["shape_judgements"]]
        case = {"id": row["id"], "split": row["split"], "annotation_status": row["review_status"],
                "source_sha256": text_hash(text), "request": make_request(source, context),
                "annotations": annotations, "notes": row["notes"], "non_actions": row["non_actions"]}
        case["annotation_digest"] = digest(annotations)
        compiled.append(case)
    if {row["split"] for row in rows} != SPLITS:
        raise ValueError("All four evaluation splits required")
    return compiled


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def read_jsonl(path):
    with Path(path).open() as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise ValueError(f"Invalid JSONL at line {number}") from exc
