import hashlib
import json
from typing import Any

from dispatch.models import DispatchOutlineNode
from writing.models import WorkingDocument, WritingAnalysisSession, WritingPiece


def canonical_json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_source_revision_hash(*, title: str, excerpt: str, body_json: dict) -> str:
    payload = {
        "title": title or "",
        "excerpt": excerpt or "",
        "body_json": body_json or {},
    }
    digest = hashlib.sha256(canonical_json_dumps(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def get_export_source_for_user(piece: WritingPiece, user) -> dict[str, Any]:
    wc = WorkingDocument.objects.filter(piece=piece, user=user).first()

    if not wc and piece.author_id != getattr(user, "id", None):
        wc = WorkingDocument.objects.filter(piece=piece, user=piece.author).first()

    if wc:
        return {
            "title": wc.title or piece.title or "",
            "excerpt": wc.excerpt or piece.excerpt or "",
            "body_json": wc.body_json or piece.body_json or {},
            "working_document_id": str(wc.id),
            "source_kind": "working_document",
        }

    return {
        "title": piece.title or "",
        "excerpt": piece.excerpt or "",
        "body_json": piece.body_json or {},
        "working_document_id": None,
        "source_kind": "writing_piece",
    }


def _extract_text_from_node(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    if node.get("type") == "text":
        return node.get("text", "") or ""
    content = node.get("content") or []
    return "".join(_extract_text_from_node(child) for child in content)


def _count_words(text: str) -> int:
    return len([part for part in text.split() if part.strip()])


def _markdown_for_node(node: dict[str, Any] | None) -> str:
    if not node:
        return ""

    node_type = node.get("type")
    text = _extract_text_from_node(node).strip()
    attrs = node.get("attrs") or {}

    if node_type == "heading":
        level = int(attrs.get("level") or 1)
        return f"{'#' * max(1, min(level, 6))} {text}".rstrip()

    if node_type == "paragraph":
        return text

    if node_type == "bulletList":
        lines: list[str] = []
        for item in node.get("content") or []:
            item_text = _extract_text_from_node(item).strip()
            lines.append(f"- {item_text}".rstrip())
        return "\n".join(lines)

    if node_type == "orderedList":
        lines = []
        for idx, item in enumerate(node.get("content") or [], start=1):
            item_text = _extract_text_from_node(item).strip()
            lines.append(f"{idx}. {item_text}".rstrip())
        return "\n".join(lines)

    if node_type == "blockquote":
        return "\n".join(f"> {line}" for line in (text.splitlines() or [text]) if line)

    if node_type == "codeBlock":
        return f"```\n{text}\n```".rstrip()

    if node_type == "horizontalRule":
        return "---"

    if node_type == "image":
        src = attrs.get("src") or ""
        alt = attrs.get("alt") or ""
        return f"![{alt}]({src})"

    if node_type == "table":
        rows = node.get("content") or []
        if not rows:
            return ""
        rendered_rows: list[str] = []
        for row in rows:
            cells = row.get("content") or []
            parts = [_extract_text_from_node(cell).strip() for cell in cells]
            rendered_rows.append("| " + " | ".join(parts) + " |")
        if len(rendered_rows) > 1:
            header_cells = rendered_rows[0].count("|") - 1
            rendered_rows.insert(1, "| " + " | ".join(["---"] * max(1, header_cells - 1)) + " |")
        return "\n".join(rendered_rows)

    return text


def _classify_block_kind(node: dict[str, Any] | None) -> str:
    node_type = (node or {}).get("type")
    mapping = {
        "heading": "heading",
        "paragraph": "paragraph",
        "bulletList": "bullet_list",
        "orderedList": "ordered_list",
        "blockquote": "blockquote",
        "codeBlock": "code_block",
        "horizontalRule": "horizontal_rule",
        "table": "table",
        "image": "image",
        "embed": "media_embed",
        "video": "media_embed",
    }
    return mapping.get(node_type, "unknown")


def _persistent_outline_payload(piece: WritingPiece) -> list[dict[str, Any]]:
    nodes = DispatchOutlineNode.objects.filter(writing_piece=piece).order_by("parent_id", "order_index", "created_at")
    return [
        {
            "id": str(node.id),
            "title": node.title,
            "parent_id": str(node.parent_id) if node.parent_id else None,
            "order_index": node.order_index,
            "anchor_target": str(node.anchor_target) if node.anchor_target else None,
        }
        for node in nodes
    ]


def build_analysis_export(*, piece: WritingPiece, title: str, excerpt: str, body_json: dict, source_revision_hash: str, source_kind: str, working_document_id: str | None = None) -> dict[str, Any]:
    content_nodes = (body_json or {}).get("content") or []
    blocks: list[dict[str, Any]] = []
    detected_headings: list[dict[str, Any]] = []
    pending_outline_marker_id: str | None = None

    for top_level_index, node in enumerate(content_nodes):
        node_type = node.get("type")
        attrs = node.get("attrs") or {}

        if node_type == "outlineMarker":
            marker_id = attrs.get("nodeId") or attrs.get("id")
            pending_outline_marker_id = str(marker_id) if marker_id else None
            continue

        block_id = attrs.get("data-block-id")
        id_strategy = "data_block_id"
        id_confidence = "high"
        if not block_id:
            fingerprint = hashlib.sha256(
                canonical_json_dumps(
                    {
                        "source_revision_hash": source_revision_hash,
                        "top_level_index": top_level_index,
                        "node_type": node_type,
                        "heading_level": attrs.get("level"),
                        "text": _extract_text_from_node(node).strip(),
                    }
                ).encode("utf-8")
            ).hexdigest()[:12]
            block_id = f"blk_{top_level_index:04d}_{fingerprint}"
            id_strategy = "fingerprint"
            id_confidence = "medium"

        text = _extract_text_from_node(node).strip()
        block = {
            "block_id": str(block_id),
            "kind": _classify_block_kind(node),
            "text": text,
            "markdown": _markdown_for_node(node),
            "word_count": _count_words(text),
            "node_json": node,
            "anchors": {
                "top_level_index": top_level_index,
                "data_block_id": attrs.get("data-block-id"),
                "outline_marker_id": pending_outline_marker_id,
            },
            "structure": {
                "heading_level": attrs.get("level") if node_type == "heading" else None,
                "list_type": "bullet" if node_type == "bulletList" else "ordered" if node_type == "orderedList" else None,
            },
            "metadata": {
                "is_empty": not bool(text or node_type in {"image", "table", "horizontalRule"}),
                "has_marks": '"marks"' in canonical_json_dumps(node),
            },
            "provenance": {
                "id_strategy": id_strategy,
                "id_confidence": id_confidence,
            },
        }
        blocks.append(block)

        if node_type == "heading":
            detected_headings.append(
                {
                    "block_id": str(block_id),
                    "text": text or "(untitled heading)",
                    "level": int(attrs.get("level") or 1),
                }
            )

        pending_outline_marker_id = None

    block_order = [block["block_id"] for block in blocks]
    normalized_markdown = "\n\n".join(block["markdown"] for block in blocks if block["markdown"]).strip()
    plain_text = " ".join(block["text"] for block in blocks if block["text"]).strip()
    persistent_nodes = _persistent_outline_payload(piece)

    if persistent_nodes and detected_headings:
        outline_mode = "mixed"
    elif persistent_nodes:
        outline_mode = "persistent"
    elif detected_headings:
        outline_mode = "detected"
    else:
        outline_mode = "none"

    return {
        "version": WritingAnalysisSession.EXPORT_VERSION_V1,
        "piece": {
            "id": str(piece.id),
            "title": title,
            "excerpt": excerpt,
            "status": piece.status,
            "enable_outline": piece.enable_outline,
        },
        "source": {
            "body_json_revision_hash": source_revision_hash,
            "source_kind": source_kind,
            "working_document_id": working_document_id,
            "exported_at": None,
            "sponsor": {
                "type": piece.sponsor_content_type.model if piece.sponsor_content_type else None,
                "id": str(piece.sponsor_object_id) if piece.sponsor_object_id else None,
                "slug": getattr(piece.sponsor, "slug", None) if piece.sponsor else None,
            },
        },
        "outline": {
            "mode": outline_mode,
            "detected_headings": detected_headings,
            "persistent_nodes": persistent_nodes,
        },
        "document": {
            "block_order": block_order,
            "blocks": blocks,
        },
        "derived": {
            "normalized_markdown": normalized_markdown,
            "plain_text": plain_text,
            "stats": {
                "block_count": len(blocks),
                "word_count": sum(block["word_count"] for block in blocks),
                "heading_count": len(detected_headings),
            },
        },
    }
