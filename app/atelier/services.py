import re

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from classifications.models import Category, Tag, ClassificationUsage

# ---------------------------------------------------------------------------
# Marker detection
# ---------------------------------------------------------------------------

# Matches /word markers AND single-char signal markers /! /~ /? /@
_MARKER_RE = re.compile(r'(?<![:/])(?:^|(?<=\s))/([!~?@]|[a-zA-Z][a-zA-Z0-9_-]*)', re.MULTILINE)
_CODE_FENCE_RE = re.compile(r'```[\s\S]*?```')
_INLINE_CODE_RE = re.compile(r'`[^`\n]+`')
_URL_RE = re.compile(r'https?://\S+')
_QUOTED_LABEL_RE = re.compile(r'^"([^"]+)"')


def _excluded_ranges(text: str) -> list[tuple[int, int]]:
    ranges = []
    for pattern in (_CODE_FENCE_RE, _INLINE_CODE_RE, _URL_RE):
        for m in pattern.finditer(text):
            ranges.append((m.start(), m.end()))
    return ranges


def _is_excluded(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in ranges)


def _extract_block(text: str, match_start: int) -> tuple[str, str, str]:
    """
    From match_start, extract raw_marker through the next blank line (or EOF),
    and attempt to auto-parse suggested label and body.
    Returns (raw_marker, suggested_label, suggested_body).
    """
    rest = text[match_start:]
    blank = rest.find('\n\n')
    raw_marker = rest[:blank].rstrip() if blank != -1 else rest.rstrip()

    word_match = re.match(r'/(?:[!~?@]|[a-zA-Z][a-zA-Z0-9_-]*)', raw_marker)
    after_word = raw_marker[word_match.end():].lstrip() if word_match else ""

    quoted = _QUOTED_LABEL_RE.match(after_word)
    if quoted:
        label = quoted.group(1)
        body = after_word[quoted.end():].strip()
    else:
        label = ""
        body = after_word.strip()

    return raw_marker, label, body


def detect_and_sync_markers(piece) -> list:
    """
    Scan piece.body for /word markers. Create pending WritingMarkerOccurrence
    records for new detections; update raw text if changed; remove pending
    records that no longer appear in the body. Returns pending occurrences.
    """
    from .models import WritingMarkerOccurrence

    body = piece.body or ""
    excluded = _excluded_ranges(body)

    detected = []
    for m in _MARKER_RE.finditer(body):
        if _is_excluded(m.start(), excluded):
            continue
        char_offset = m.start()
        raw_name = m.group(1)
        raw_marker, label, body_text = _extract_block(body, char_offset)
        detected.append({
            "raw_name": raw_name,
            "char_offset": char_offset,
            "raw_marker": raw_marker,
            "suggested_label": label,
            "suggested_body": body_text,
        })

    # Resolve sponsor from piece ownership
    sponsor_ct = piece.sponsor_content_type
    sponsor_id = piece.sponsor_object_id
    if sponsor_ct is None:
        from users.models import CustomUser
        sponsor_ct = ContentType.objects.get_for_model(CustomUser)
        sponsor_id = piece.author_id

    existing = {
        occ.char_offset: occ
        for occ in WritingMarkerOccurrence.objects.filter(piece=piece)
    }
    detected_offsets = {d["char_offset"] for d in detected}

    # Remove pending occurrences that are no longer in the body
    for offset, occ in existing.items():
        if offset not in detected_offsets and occ.status == WritingMarkerOccurrence.STATUS_PENDING:
            occ.delete()

    # Create or refresh
    for d in detected:
        offset = d["char_offset"]
        if offset in existing:
            occ = existing[offset]
            if occ.status == WritingMarkerOccurrence.STATUS_PENDING and occ.raw_marker != d["raw_marker"]:
                occ.raw_marker = d["raw_marker"]
                occ.raw_name = d["raw_name"]
                occ.save(update_fields=["raw_marker", "raw_name", "updated_at"])
        else:
            WritingMarkerOccurrence.objects.create(
                piece=piece,
                raw_name=d["raw_name"],
                char_offset=offset,
                raw_marker=d["raw_marker"],
                label=d["suggested_label"],
                body=d["suggested_body"],
                sponsor_content_type=sponsor_ct,
                sponsor_object_id=sponsor_id,
            )

    return list(
        WritingMarkerOccurrence.objects.filter(piece=piece, status=WritingMarkerOccurrence.STATUS_PENDING)
        .order_by("char_offset")
    )


def compute_craft_readiness(writing_piece) -> dict:
    """
    Computes readiness state for five Atelier dimensions.
    Returns a dict; states are "untouched" | "partial" | "confirmed" | "deferred".
    """
    piece_ct = ContentType.objects.get_for_model(writing_piece)
    piece_id = str(writing_piece.pk)

    tag_ct = ContentType.objects.get_for_model(Tag)
    cat_ct = ContentType.objects.get_for_model(Category)

    tag_count = ClassificationUsage.objects.filter(
        classification_client_content_type=piece_ct,
        classification_client_object_id=piece_id,
        classification_content_type=tag_ct,
    ).count()

    cat_count = ClassificationUsage.objects.filter(
        classification_client_content_type=piece_ct,
        classification_client_object_id=piece_id,
        classification_content_type=cat_ct,
    ).count()

    synopsis = getattr(writing_piece, "synopsis", None)

    tags = "confirmed" if tag_count >= 1 else "untouched"
    category = "confirmed" if cat_count >= 1 else "untouched"
    series = "confirmed" if writing_piece.series_id else "untouched"

    from relations.service import RelationshipService
    outgoing = RelationshipService.get_outgoing(writing_piece, domain="editorial")
    if not outgoing.exists():
        relations = "untouched"
    elif outgoing.filter(lifecycle__in=("acknowledged", "mutual")).exists():
        relations = "confirmed"
    else:
        relations = "partial"

    if synopsis is None:
        summaries = "untouched"
    else:
        confirmed = any([
            synopsis.public_synopsis_confirmed,
            synopsis.linkedin_synopsis_confirmed,
            synopsis.internal_abstract_confirmed,
        ])
        has_text = any([
            bool(synopsis.description),
            bool(synopsis.linkedin_copy),
            bool(synopsis.internal_abstract),
        ])
        if confirmed:
            summaries = "confirmed"
        elif has_text:
            summaries = "partial"
        else:
            summaries = "untouched"

    active = [tags, category, summaries, series, relations]
    if all(s == "confirmed" for s in active):
        overall = "confirmed"
    elif any(s in ("confirmed", "partial") for s in active):
        overall = "partial"
    else:
        overall = "untouched"

    return {
        "tags": tags,
        "category": category,
        "summaries": summaries,
        "series": series,
        "relations": relations,
        "overall": overall,
    }


def get_readiness_warnings(writing_piece) -> list[str]:
    """
    Returns human-readable warning strings for untouched readiness dimensions.
    Used at publish time (warn-not-block).
    """
    readiness = compute_craft_readiness(writing_piece)
    warnings = []

    if readiness["tags"] == "untouched":
        warnings.append("No tags have been added to this piece.")
    if readiness["category"] == "untouched":
        warnings.append("No category has been set for this piece.")
    if readiness["summaries"] == "untouched":
        warnings.append("No summaries have been written for this piece.")
    if readiness["series"] == "untouched":
        warnings.append("This piece is not part of any series.")

    return warnings
