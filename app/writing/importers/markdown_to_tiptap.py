"""
Convert markdown files to TipTap/ProseMirror JSON.

This is intentionally deterministic for import use.
It supports common local authoring structures used in article drafts:

- YAML frontmatter
- headings
- paragraphs
- blockquotes
- ordered and unordered lists
- horizontal rules
- fenced code blocks
- inline bold / italic / code / links
- table-like markdown (flattened to paragraph rows for now)

The goal is a stable draft import path into the editor, not a full CommonMark
implementation.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import yaml


FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
UNORDERED_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
HR_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
BLOCKQUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
FENCED_CODE_RE = re.compile(r"^```(?P<lang>[A-Za-z0-9_-]+)?\s*$")
TABLE_DIVIDER_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")


def parse_markdown_file(source: str | bytes | Path, filename: str | None = None) -> dict[str, Any]:
    text = _read_markdown_source(source)
    frontmatter, body_markdown, warnings = extract_frontmatter(text)
    body_json, body_warnings = markdown_to_tiptap(body_markdown)
    title = resolve_title(frontmatter, body_markdown, filename)
    excerpt = resolve_excerpt(frontmatter, body_markdown)
    return {
        "frontmatter": frontmatter,
        "body_markdown": body_markdown,
        "body_json": body_json,
        "title": title,
        "excerpt": excerpt,
        "warnings": warnings + body_warnings,
    }


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str, list[str]]:
    if not text.startswith("---"):
        return {}, text, []

    lines = text.splitlines()
    if not lines or not FRONTMATTER_BOUNDARY.match(lines[0]):
        return {}, text, []

    closing_idx = None
    for idx in range(1, len(lines)):
        if FRONTMATTER_BOUNDARY.match(lines[idx]):
            closing_idx = idx
            break

    if closing_idx is None:
        return {}, text, ["Frontmatter start detected but closing delimiter was not found."]

    frontmatter_text = "\n".join(lines[1:closing_idx])
    body_markdown = "\n".join(lines[closing_idx + 1 :]).lstrip("\n")

    try:
        parsed = yaml.safe_load(frontmatter_text) or {}
    except Exception as exc:  # noqa: BLE001
        return {}, body_markdown, [f"Failed to parse YAML frontmatter: {exc}"]

    if not isinstance(parsed, dict):
        return {}, body_markdown, ["Frontmatter was parsed but did not produce a mapping."]

    return parsed, body_markdown, []


def markdown_to_tiptap(markdown_text: str) -> tuple[dict[str, Any], list[str]]:
    lines = markdown_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    content: list[dict[str, Any]] = []
    warnings: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        fenced_match = FENCED_CODE_RE.match(line)
        if fenced_match:
            language = fenced_match.group("lang") or None
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not FENCED_CODE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines) and FENCED_CODE_RE.match(lines[i]):
                i += 1
            content.append(
                {
                    "type": "codeBlock",
                    "attrs": {"language": language},
                    "content": [{"type": "text", "text": "\n".join(code_lines)}] if code_lines else [],
                }
            )
            continue

        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            content.append(_heading_node(heading_match.group(2), level))
            i += 1
            continue

        if HR_RE.match(line):
            content.append({"type": "horizontalRule"})
            i += 1
            continue

        if BLOCKQUOTE_RE.match(line):
            quote_lines: list[str] = []
            while i < len(lines):
                block_match = BLOCKQUOTE_RE.match(lines[i])
                if not block_match:
                    break
                quote_lines.append(block_match.group(1))
                i += 1
            quote_text = " ".join(part.strip() for part in quote_lines if part.strip())
            if clean_inline_text(quote_text):
                content.append(
                    {
                        "type": "blockquote",
                        "attrs": {"data-block-id": str(uuid.uuid4())},
                        "content": [_paragraph_node(quote_text)],
                    }
                )
            continue

        unordered_match = UNORDERED_RE.match(line)
        ordered_match = ORDERED_RE.match(line)
        if unordered_match or ordered_match:
            ordered = bool(ordered_match)
            items: list[dict[str, Any]] = []
            matcher = ORDERED_RE if ordered else UNORDERED_RE
            while i < len(lines):
                item_match = matcher.match(lines[i])
                if not item_match:
                    break
                item_text = item_match.group(1)
                if clean_inline_text(item_text):
                    items.append(
                        {
                            "type": "listItem",
                            "content": [_paragraph_node(item_text)],
                        }
                    )
                i += 1
            if items:
                content.append(
                    {
                        "type": "orderedList" if ordered else "bulletList",
                        "content": items,
                    }
                )
            continue

        if "|" in line and i + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[i + 1]):
            warnings.append("Markdown table detected and flattened to plain-text rows.")
            table_lines = [line.strip()]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i].strip())
                i += 1
            for row in table_lines:
                content.append(_paragraph_node(row))
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.strip()
            if (
                not next_stripped
                or HEADING_RE.match(next_line)
                or HR_RE.match(next_line)
                or FENCED_CODE_RE.match(next_line)
                or BLOCKQUOTE_RE.match(next_line)
                or UNORDERED_RE.match(next_line)
                or ORDERED_RE.match(next_line)
                or ("|" in next_line and i + 1 < len(lines) and TABLE_DIVIDER_RE.match(lines[i + 1]))
            ):
                break
            paragraph_lines.append(next_stripped)
            i += 1

        paragraph_text = " ".join(paragraph_lines)
        if clean_inline_text(paragraph_text):
            content.append(_paragraph_node(paragraph_text))

    if not content:
        content.append({"type": "paragraph", "attrs": {"data-block-id": str(uuid.uuid4())}})

    return {"type": "doc", "content": content}, warnings


def resolve_title(frontmatter: dict[str, Any], body_markdown: str, filename: str | None = None) -> str:
    frontmatter_title = frontmatter.get("title")
    if isinstance(frontmatter_title, str) and frontmatter_title.strip():
        return frontmatter_title.strip()

    for line in body_markdown.splitlines():
        match = HEADING_RE.match(line)
        if match:
            return clean_inline_text(match.group(2))

    if filename:
        return Path(filename).stem.replace("-", " ").replace("_", " ").strip()
    return ""


def resolve_excerpt(frontmatter: dict[str, Any], body_markdown: str) -> str:
    summary = frontmatter.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", body_markdown) if chunk.strip()]
    for chunk in chunks:
        if HEADING_RE.match(chunk):
            continue
        cleaned = clean_inline_text(chunk.replace("\n", " "))
        if cleaned:
            return cleaned[:320]
    return ""


def clean_inline_text(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _paragraph_node(text: str) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "attrs": {"data-block-id": str(uuid.uuid4())},
        "content": _inline_nodes(text),
    }


def _heading_node(text: str, level: int) -> dict[str, Any]:
    return {
        "type": "heading",
        "attrs": {"level": level, "data-block-id": str(uuid.uuid4())},
        "content": _inline_nodes(text),
    }


def _read_markdown_source(source: str | bytes | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace")
    if isinstance(source, str):
        maybe_path = Path(source)
        if maybe_path.exists():
            return maybe_path.read_text(encoding="utf-8")
        return source
    raise TypeError(f"Unsupported markdown source type: {type(source)!r}")


def _inline_nodes(text: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    pos = 0
    pattern = re.compile(
        r"(!?\[[^\]]+\]\([^)]+\))|(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*]+\*)|(_[^_]+_)"
    )

    for match in pattern.finditer(text):
        start, end = match.span()
        if start > pos:
            nodes.append({"type": "text", "text": text[pos:start]})

        token = match.group(0)
        if token.startswith("!["):
            alt = re.sub(r"^!\[([^\]]*)\]\([^)]+\)$", r"\1", token)
            if alt:
                nodes.append({"type": "text", "text": alt})
        elif token.startswith("["):
            label_match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if label_match:
                label, href = label_match.groups()
                nodes.append(
                    {
                        "type": "text",
                        "text": label,
                        "marks": [{"type": "link", "attrs": {"href": href, "target": "_blank"}}],
                    }
                )
        elif token.startswith("`"):
            nodes.append(
                {
                    "type": "text",
                    "text": token[1:-1],
                    "marks": [{"type": "code"}],
                }
            )
        elif token.startswith("**") or token.startswith("__"):
            nodes.append(
                {
                    "type": "text",
                    "text": token[2:-2],
                    "marks": [{"type": "bold"}],
                }
            )
        elif token.startswith("*") or token.startswith("_"):
            nodes.append(
                {
                    "type": "text",
                    "text": token[1:-1],
                    "marks": [{"type": "italic"}],
                }
            )
        pos = end

    if pos < len(text):
        nodes.append({"type": "text", "text": text[pos:]})

    return [node for node in nodes if node.get("text")]
