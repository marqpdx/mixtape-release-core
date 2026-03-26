# writing/synopsis_service.py
"""
SynopsisGenerationService — rule-based synopsis generation for WritingPiece.

Never blocks publication. Falls back gracefully at every step.
AI-assisted generation (teaser/description/commentary) deferred to a later phase.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TEASER_MAX = 220
DESCRIPTION_MAX = 500


def _extract_plain_text(body_json: dict, char_limit: int = 600) -> str:
    """Walk a ProseMirror/TipTap doc and extract plain text up to char_limit."""
    if not body_json or not isinstance(body_json, dict):
        return ""

    parts: list[str] = []
    total = 0

    def walk(node):
        nonlocal total
        if total >= char_limit:
            return
        node_type = node.get("type", "")
        if node_type == "text":
            text = node.get("text", "")
            parts.append(text)
            total += len(text)
        for child in node.get("content", []):
            if total >= char_limit:
                break
            walk(child)

    walk(body_json)
    return " ".join(parts)[:char_limit].strip()


def _derive_canonical_url(piece) -> str:
    if piece.canonical_url:
        return piece.canonical_url
    base = getattr(settings, "SITE_BASE_URL", "https://mixtape.social")
    group = piece.group
    if group:
        return f"{base}/groups/{group.slug}/writing/{piece.slug}"
    return f"{base}/writing/{piece.slug}"


def _derive_teaser(piece) -> str:
    """Short single-line summary — prefer excerpt, fall back to body text."""
    if piece.excerpt:
        return piece.excerpt[:TEASER_MAX]
    body_text = _extract_plain_text(piece.body_json or {}, TEASER_MAX)
    return body_text[:TEASER_MAX]


def _derive_description(piece) -> str:
    """Fuller description — excerpt or slightly longer body extract."""
    if piece.excerpt:
        return piece.excerpt[:DESCRIPTION_MAX]
    body_text = _extract_plain_text(piece.body_json or {}, DESCRIPTION_MAX)
    return body_text[:DESCRIPTION_MAX]


def _derive_thumbnail(piece) -> str:
    """Walk body_json for the first image node URL."""
    body = piece.body_json
    if not body or not isinstance(body, dict):
        return ""

    def find_image(node):
        if node.get("type") == "image":
            src = node.get("attrs", {}).get("src", "")
            if src:
                return src
        for child in node.get("content", []):
            result = find_image(child)
            if result:
                return result
        return ""

    return find_image(body)


def _derive_author_name(piece) -> str:
    author = piece.author
    if not author:
        return ""
    return (
        getattr(author, "display_name", None)
        or author.get_full_name()
        or author.username
    )


def _derive_sponsor_name(piece) -> str:
    group = piece.group
    if group:
        return getattr(group, "name", "") or getattr(group, "title", "")
    return _derive_author_name(piece)


def _derive_sponsor_type(piece) -> str:
    if piece.group:
        return "group"
    return "user"


class SynopsisGenerationService:

    @classmethod
    def generate_for_piece(cls, piece) -> "WritingSynopsis | None":
        """
        Generate (or regenerate) a WritingSynopsis for the given piece.

        Safe to call after publish — never raises, never blocks.
        Returns the Synopsis instance, or None if something went badly wrong.
        """
        from writing.models import WritingSynopsis

        try:
            canonical_url = _derive_canonical_url(piece)
            title = piece.title or ""
            teaser = _derive_teaser(piece)
            description = _derive_description(piece)
            thumbnail_url = _derive_thumbnail(piece)
            author_name = _derive_author_name(piece)
            sponsor_name = _derive_sponsor_name(piece)
            sponsor_type = _derive_sponsor_type(piece)
            published_at = piece.published_at or timezone.now()
            source_version = piece.current_version_no or 1

            synopsis, _ = WritingSynopsis.objects.update_or_create(
                piece=piece,
                defaults={
                    "canonical_url": canonical_url,
                    "title": title,
                    "teaser": teaser,
                    "description": description,
                    "commentary": "",
                    "thumbnail_url": thumbnail_url,
                    "hero_image_url": "",
                    "author_name": author_name,
                    "sponsor_name": sponsor_name,
                    "sponsor_type": sponsor_type,
                    "published_at": published_at,
                    "visibility": "public",
                    "status": "active",
                    "source_version": source_version,
                    "generated_by": "rule_based",
                },
            )
            return synopsis

        except Exception:
            logger.exception(
                "SynopsisGenerationService.generate_for_piece failed for piece %s",
                getattr(piece, "id", "unknown"),
            )
            return None
