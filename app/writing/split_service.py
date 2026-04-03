# writing/split_service.py
#
# Phase 4: deterministic split execution.
# Reads confirmed splitMarker nodes from a WorkingDocument, creates
# new WritingPiece(s), builds a WorkSession + WritingSurfaceDocument,
# and marks any active SplitSuggestion as executed.
#
# No AI calls here — all AI work happened in Phase 2.

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class SplitError(Exception):
    """Raised when split execution is not possible."""


@transaction.atomic
def execute_split(piece, user):
    """
    Execute split markers in the user's working copy of `piece`.

    Steps:
      1. Load WorkingDocument for (piece, user)
      2. Parse content nodes into segments at splitMarker boundaries
      3. Create a new WritingPiece for each non-anchor segment
      4. Create WorkSession + WritingSurfaceDocument with segmentBoundary nodes
      5. Register new pieces as WorkSessionItems
      6. Update the anchor's WorkingDocument to the first segment only
      7. Mark any active SplitSuggestion as 'executed'

    Returns the newly created WorkSession.
    Raises SplitError if no working copy or no split markers found.
    """
    from writing.models import SplitSuggestion, WorkingDocument, WritingPiece
    from worksessions.models import WorkSession, WritingSurfaceDocument
    from worksessions.services import add_session_item

    # 1. Load working copy
    wc = WorkingDocument.objects.filter(piece=piece, user=user).first()
    if not wc or not wc.body_json:
        raise SplitError("No working copy found for this piece.")

    content_nodes = wc.body_json.get("content", [])

    # 2. Parse segments at splitMarker boundaries
    segments = _extract_segments(content_nodes)

    if len(segments) < 2:
        raise SplitError("No split markers found in working copy.")

    logger.info(
        "[split] Executing split for piece %s: %d segment(s)", piece.pk, len(segments)
    )

    # 3. Create new WritingPiece for each non-anchor segment
    new_pieces = []
    for seg in segments[1:]:
        marker_attrs = seg["marker"] or {}
        title = (marker_attrs.get("title") or "").strip()

        new_piece = WritingPiece.objects.create(
            author=piece.author,
            sponsor_content_type=piece.sponsor_content_type,
            sponsor_object_id=piece.sponsor_object_id,
            writing_kind=piece.writing_kind,
            title=title,
            addressed_to=piece.addressed_to,
            body_json={"type": "doc", "content": seg["nodes"]},
        )
        new_pieces.append(new_piece)
        logger.info("[split] Created new piece %s (title=%r)", new_piece.pk, title or "(untitled)")

    # 4. Build the WritingSurfaceDocument body
    #    Anchor segment first, then segmentBoundary + new-piece nodes for each split
    surface_content = list(segments[0]["nodes"])

    for new_piece, seg in zip(new_pieces, segments[1:]):
        surface_content.append({
            "type": "segmentBoundary",
            "attrs": {
                "artifactType": "writingpiece",
                "artifactId": str(new_piece.pk),
                "isAnchorReturn": False,
            },
        })
        surface_content.extend(seg["nodes"])

    surface_body = {"type": "doc", "content": surface_content}

    # Create the surface document and session
    anchor_ct = ContentType.objects.get_for_model(piece)
    surface = WritingSurfaceDocument.objects.create(body_json=surface_body)

    session = WorkSession.objects.create(
        owner=user,
        anchor_content_type=anchor_ct,
        anchor_object_id=piece.pk,
        surface_document=surface,
    )

    # 5. Register new pieces as session items
    for new_piece in new_pieces:
        add_session_item(session, new_piece)

    # 6. Update anchor's working copy to the first segment only
    #    (checkpoint_extraction will keep it consistent if session is used,
    #     but pre-update ensures correctness if session is abandoned)
    anchor_nodes = segments[0]["nodes"]
    wc.body_json = {"type": "doc", "content": anchor_nodes}
    wc.save(update_fields=["body_json", "updated_at"])

    # 7. Mark active SplitSuggestion as executed
    SplitSuggestion.objects.filter(piece=piece).exclude(
        status__in=["superseded", "declined", "executed"]
    ).update(status="executed", updated_at=timezone.now())

    return session


def _extract_segments(content_nodes):
    """
    Walk TipTap content nodes and split at splitMarker boundaries.

    Returns a list of segment dicts:
      {
        "marker": dict | None,   # attrs of the preceding splitMarker (None for first segment)
        "nodes":  list[dict],    # content nodes in this segment
      }

    The first segment is always the anchor (no preceding marker).
    """
    segments = []
    current_nodes = []
    current_marker = None

    for node in content_nodes:
        if node.get("type") == "splitMarker":
            # Close the current segment and start a new one
            segments.append({"marker": current_marker, "nodes": current_nodes})
            current_nodes = []
            current_marker = node.get("attrs", {})
        else:
            current_nodes.append(node)

    # Final (or only) segment
    segments.append({"marker": current_marker, "nodes": current_nodes})

    return segments
