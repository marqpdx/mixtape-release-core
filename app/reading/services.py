from django.utils import timezone

from utils.writing.writing_utils import extract_text_from_prosemirror

from .models import Dart, ReadingStats


# ---------------------------------------------------------------------------
# Anchoring (RO-3)
# ---------------------------------------------------------------------------

def resolve_anchor(dart: Dart, piece_body_json: dict) -> dict:
    """
    Returns resolved anchor position for a Dart against the current piece body.

    Resolution order:
      1. Text-match — find selected_text in current body (primary)
      2. Offset fallback — use stored offsets if text not found
      3. Document fallback — fall back to document-level if anchor text is gone
    """
    if dart.anchor_type == Dart.ANCHOR_DOCUMENT or not dart.selected_text:
        return {
            "anchor_type": "document",
            "start": 0,
            "end": 0,
            "selected_text": None,
            "resolved": "document",
        }

    body_text = extract_text_from_prosemirror(piece_body_json) if piece_body_json else ""

    idx = body_text.find(dart.selected_text)
    if idx != -1:
        return {
            "anchor_type": "selection",
            "start": idx,
            "end": idx + len(dart.selected_text),
            "selected_text": dart.selected_text,
            "resolved": "text_match",
        }

    if dart.anchor_start_offset > 0:
        return {
            "anchor_type": "selection",
            "start": dart.anchor_start_offset,
            "end": dart.anchor_end_offset,
            "selected_text": dart.selected_text,
            "resolved": "offset_fallback",
        }

    return {
        "anchor_type": "document",
        "start": 0,
        "end": 0,
        "selected_text": None,
        "resolved": "document_fallback",
    }


# ---------------------------------------------------------------------------
# ReadingStats (RO-4)
# ---------------------------------------------------------------------------

def record_read(*, user, artifact) -> ReadingStats:
    """
    Record or update a read event for user + artifact.
    Called when a reader opens a piece. Safe to call multiple times.
    """
    stats, _ = ReadingStats.objects.get_or_create(user=user, artifact=artifact)
    now = timezone.now()
    if not stats.first_read_at:
        stats.first_read_at = now
    stats.last_read_at = now
    stats.times_read += 1
    stats.save(update_fields=["first_read_at", "last_read_at", "times_read", "updated_at"])
    return stats
