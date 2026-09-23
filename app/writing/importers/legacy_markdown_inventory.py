"""Read-only inventory and conversion preview for legacy Markdown archives."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1
LEGACY_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z ]*):\s*(.*)$")
TEXT_SUFFIXES = (
    ".md",
    ".mdx",
    ".draft",
    ".md-draft",
    ".me",
)


def inventory_legacy_archive(source_root: str | Path) -> dict[str, Any]:
    """Return a deterministic review manifest without modifying the archive."""
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Archive directory does not exist: {root}")

    items = [_inventory_file(path, root) for path in sorted(root.rglob("*")) if path.is_file()]
    _annotate_duplicates(items, "sha256", "exact_duplicate_paths")
    _annotate_duplicates(items, "normalized_body_sha256", "normalized_body_duplicate_paths")

    for item in items:
        if item["exact_duplicate_paths"]:
            item["warnings"].append("Exact duplicate content exists elsewhere in the archive.")
        elif item["normalized_body_duplicate_paths"]:
            item["warnings"].append("Equivalent normalized body exists elsewhere in the archive.")

    return {
        "schema_version": SCHEMA_VERSION,
        "source_root": str(root),
        "summary": _summarize(items),
        "items": items,
    }


def _inventory_file(path: Path, root: Path) -> dict[str, Any]:
    relative_path = path.relative_to(root).as_posix()
    raw = path.read_bytes()
    item: dict[str, Any] = {
        "source_path": relative_path,
        "filename": path.name,
        "source_section": relative_path.split("/", 1)[0] if "/" in relative_path else "<root>",
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_format": "binary_or_unsupported",
        "source_status_hint": "draft" if ".draft" in path.name.lower() else "unknown",
        "publication_decision": "review_required",
        "metadata": {},
        "proposed": {},
        "body_preview": "",
        "normalized_body_sha256": None,
        "exact_duplicate_paths": [],
        "normalized_body_duplicate_paths": [],
        "warnings": [],
    }

    if not _looks_like_text_document(path):
        item["warnings"].append("Unsupported file type; retained in inventory but not conversion preview.")
        return item

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        item["warnings"].append("File is not valid UTF-8 text.")
        return item

    metadata, body, content_format, parse_warnings = parse_legacy_document(text)
    item["content_format"] = content_format
    item["metadata"] = metadata
    item["warnings"].extend(parse_warnings)

    normalized_body = re.sub(r"\s+", " ", body).strip()
    item["normalized_body_sha256"] = hashlib.sha256(normalized_body.encode("utf-8")).hexdigest()

    title = _string_value(metadata.get("title"))
    summary = _string_value(metadata.get("summary") or metadata.get("wherein"))
    authors = _list_value(metadata.get("authors") or metadata.get("author"))
    tags = _list_value(metadata.get("tags"))
    collection = _string_value(metadata.get("collection"))
    categories = _list_value(metadata.get("category"))
    original_date, date_warning = _normalize_date(metadata.get("date"))

    if not title:
        title = _title_from_filename(path.name)
        item["warnings"].append("No metadata title; proposed title comes from the filename.")
    if not summary:
        summary = _first_paragraph(body)
        if summary:
            item["warnings"].append("No summary metadata; proposed summary comes from the body.")
    if not authors:
        item["warnings"].append("No author metadata.")
    if not original_date:
        item["warnings"].append(date_warning or "No original date metadata.")
    elif date_warning:
        item["warnings"].append(date_warning)
    if item["source_status_hint"] == "draft":
        item["warnings"].append("Filename marks this source as a draft.")

    item["body_preview"] = _first_paragraph(body, limit=320)
    item["proposed"] = {
        "title": title,
        "summary": summary,
        "authors": authors,
        "original_date": original_date,
        "tags": tags,
        "collection": collection or None,
        "categories": categories,
        "source_section": item["source_section"],
        "taxonomy_review_required": True,
    }
    return item


def parse_legacy_document(text: str) -> tuple[dict[str, Any], str, str, list[str]]:
    """Parse YAML frontmatter or the old opening ``Title:`` metadata block."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    warnings: list[str] = []

    if lines and lines[0].strip() == "---":
        closing = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
        if closing is None:
            return {}, normalized, "yaml_frontmatter", ["YAML frontmatter has no closing delimiter."]
        try:
            parsed = yaml.safe_load("\n".join(lines[1:closing])) or {}
        except yaml.YAMLError as exc:
            return {}, "\n".join(lines[closing + 1 :]).lstrip("\n"), "yaml_frontmatter", [
                f"Could not parse YAML frontmatter: {exc}"
            ]
        if not isinstance(parsed, dict):
            warnings.append("YAML frontmatter is not a mapping.")
            parsed = {}
        return _normalize_metadata(parsed), "\n".join(lines[closing + 1 :]).lstrip("\n"), "yaml_frontmatter", warnings

    metadata: dict[str, Any] = {}
    index = 0
    while index < len(lines) and lines[index].strip():
        match = LEGACY_HEADER_RE.match(lines[index])
        if not match:
            break
        metadata[_normalize_key(match.group(1))] = match.group(2).strip()
        index += 1

    if metadata:
        body = "\n".join(lines[index:]).lstrip("\n")
        return metadata, body, "legacy_header", warnings
    return {}, normalized, "plain_text", warnings


def manifest_csv_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten manifest items for a spreadsheet-friendly CSV export."""
    rows = []
    for item in manifest["items"]:
        proposed = item["proposed"]
        rows.append(
            {
                "source_path": item["source_path"],
                "source_section": item["source_section"],
                "content_format": item["content_format"],
                "source_status_hint": item["source_status_hint"],
                "publication_decision": item["publication_decision"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
                "title": proposed.get("title", ""),
                "summary": proposed.get("summary", ""),
                "authors": " | ".join(proposed.get("authors", [])),
                "original_date": proposed.get("original_date") or "",
                "tags": " | ".join(proposed.get("tags", [])),
                "collection": proposed.get("collection") or "",
                "categories": " | ".join(proposed.get("categories", [])),
                "exact_duplicate_paths": " | ".join(item["exact_duplicate_paths"]),
                "normalized_body_duplicate_paths": " | ".join(item["normalized_body_duplicate_paths"]),
                "warnings": " | ".join(item["warnings"]),
                "body_preview": item["body_preview"],
            }
        )
    return rows


def _looks_like_text_document(path: Path) -> bool:
    name = path.name.lower()
    return not path.suffix or any(name.endswith(suffix) or f"{suffix}." in name for suffix in TEXT_SUFFIXES)


def _normalize_metadata(metadata: dict[Any, Any]) -> dict[str, Any]:
    return {_normalize_key(str(key)): _json_value(value) for key, value in metadata.items()}


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _normalize_date(value: Any) -> tuple[str | None, str | None]:
    raw = _string_value(value)
    if not raw:
        return None, None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(normalized)
        except ValueError:
            return None, f"Could not parse original date: {raw}"
        parsed = datetime.combine(parsed_date, datetime.min.time())
    warning = "Original date is in the future and requires review." if parsed.date() > date.today() else None
    return parsed.isoformat(), warning


def _title_from_filename(filename: str) -> str:
    stem = filename
    for ending in (".md.draft.2", ".md..draft.2", ".md.draft", ".md-draft", ".draft", ".mdx", ".md", ".me"):
        if stem.lower().endswith(ending):
            stem = stem[: -len(ending)]
            break
    return re.sub(r"[-_]+", " ", stem).strip()


def _first_paragraph(body: str, limit: int = 320) -> str:
    for block in re.split(r"\n\s*\n", body):
        cleaned = re.sub(r"\s+", " ", block).strip()
        if cleaned:
            return cleaned[:limit]
    return ""


def _annotate_duplicates(items: list[dict[str, Any]], key: str, output_key: str) -> None:
    groups: dict[str, list[str]] = defaultdict(list)
    for item in items:
        value = item.get(key)
        if value:
            groups[value].append(item["source_path"])
    for item in items:
        matches = groups.get(item.get(key), [])
        item[output_key] = [path for path in matches if path != item["source_path"]]


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    collections = Counter(
        item["proposed"].get("collection")
        for item in items
        if item["proposed"].get("collection")
    )
    sections = Counter(item["source_section"] for item in items)
    formats = Counter(item["content_format"] for item in items)
    return {
        "file_count": len(items),
        "total_bytes": sum(item["size_bytes"] for item in items),
        "draft_hint_count": sum(item["source_status_hint"] == "draft" for item in items),
        "unsupported_count": sum(item["content_format"] == "binary_or_unsupported" for item in items),
        "exact_duplicate_group_count": _duplicate_group_count(items, "sha256"),
        "normalized_body_duplicate_group_count": _duplicate_group_count(items, "normalized_body_sha256"),
        "sections": dict(sorted(sections.items(), key=lambda pair: pair[0].casefold())),
        "formats": dict(sorted(formats.items())),
        "collections": dict(sorted(collections.items(), key=lambda pair: pair[0].casefold())),
    }


def _duplicate_group_count(items: list[dict[str, Any]], key: str) -> int:
    counts = Counter(item.get(key) for item in items if item.get(key))
    return sum(count > 1 for count in counts.values())
