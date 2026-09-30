"""Deterministic text preparation for the Writing Search read model."""

import hashlib
import json

from django.contrib.postgres.search import SearchVector
from django.db import transaction

from writing.models import WorkingDocument, WritingPiece, WritingSearchDocument


BLOCK_TYPES = {
    "paragraph", "heading", "blockquote", "bulletList", "orderedList",
    "listItem", "codeBlock", "table", "tableRow", "tableCell",
}


def extract_search_text(document):
    """Flatten TipTap text without inserting spaces inside inline text runs."""
    def walk(node):
        if not isinstance(node, dict):
            return ""
        kind = node.get("type")
        if kind == "text":
            return node.get("text") or ""
        if kind == "hardBreak":
            return "\n"
        children = node.get("content") or []
        if not isinstance(children, list):
            return ""
        separator = "\n" if kind in BLOCK_TYPES and kind != "paragraph" else ""
        return separator.join(walk(child) for child in children)

    if not isinstance(document, dict):
        return ""
    blocks = document.get("content") or []
    if not isinstance(blocks, list):
        return ""
    return "\n\n".join(filter(None, (walk(block).strip() for block in blocks)))


def _source_hash(title, excerpt, body_json):
    payload = json.dumps(
        [title, excerpt, body_json], sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _refresh_vector(row):
    WritingSearchDocument.objects.filter(pk=row.pk).update(
        search_vector=(
            SearchVector("title", weight="A", config="simple")
            + SearchVector("excerpt", weight="B", config="simple")
            + SearchVector("body_text", weight="C", config="simple")
        )
    )


@transaction.atomic
def index_published_piece(piece: WritingPiece):
    """Refresh the current canonical published snapshot or remove a stale row."""
    if piece.status != "published":
        WritingSearchDocument.objects.filter(
            piece=piece, variant=WritingSearchDocument.Variant.PUBLISHED
        ).delete()
        return None

    row, _ = WritingSearchDocument.objects.update_or_create(
        piece=piece,
        variant=WritingSearchDocument.Variant.PUBLISHED,
        defaults={
            "working_document": None,
            "title": piece.title or "",
            "excerpt": piece.excerpt or "",
            "body_text": extract_search_text(piece.body_json),
            "source_updated_at": piece.updated_at,
            "source_hash": _source_hash(piece.title or "", piece.excerpt or "", piece.body_json),
        },
    )
    _refresh_vector(row)
    return row


@transaction.atomic
def index_working_document(document: WorkingDocument):
    """Refresh one persisted draft, whether solo or Dispatch-backed."""
    piece = document.piece
    title = document.title or piece.title or ""
    excerpt = document.excerpt or piece.excerpt or ""
    row, _ = WritingSearchDocument.objects.update_or_create(
        working_document=document,
        defaults={
            "piece": piece,
            "variant": WritingSearchDocument.Variant.DRAFT,
            "title": title,
            "excerpt": excerpt,
            "body_text": extract_search_text(document.body_json),
            "source_updated_at": document.last_saved_at,
            "source_hash": _source_hash(title, excerpt, document.body_json),
        },
    )
    _refresh_vector(row)
    return row
