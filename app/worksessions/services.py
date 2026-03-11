"""
Service layer for Work Sessions (Artifact Stream Authoring).

All write operations use @transaction.atomic.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .body_adapters import get_adapter
from .models import (
    ArtifactMergeRecord,
    WorkSession,
    WorkSessionItem,
    WritingSurfaceDocument,
)


@transaction.atomic
def create_work_session(owner, anchor_object):
    """
    Create a WorkSession + WritingSurfaceDocument for a composed writing flow.

    Initializes the surface body_json from the anchor's current content:
    - If a WorkingDocument exists for this user+piece, use its body_json
    - Otherwise use the anchor's canonical body

    Returns the created WorkSession.
    """
    anchor_ct = ContentType.objects.get_for_model(anchor_object)

    # Initialize surface body from anchor's current draft or canonical body
    initial_body = _get_anchor_body(anchor_object, owner)

    surface = WritingSurfaceDocument.objects.create(
        body_json=initial_body,
    )

    session = WorkSession.objects.create(
        owner=owner,
        anchor_content_type=anchor_ct,
        anchor_object_id=anchor_object.pk,
        surface_document=surface,
    )

    return session


def _get_anchor_body(anchor_object, owner):
    """
    Get the current body content for the anchor artifact.
    Tries WorkingDocument first (for WritingPiece), then canonical fields.
    """
    # WritingPiece: check for WorkingDocument
    if hasattr(anchor_object, "working_copies"):
        from writing.models import WorkingDocument

        wc = WorkingDocument.objects.filter(
            piece=anchor_object, user=owner
        ).first()
        if wc and wc.body_json:
            return wc.body_json

    # WritingPiece canonical body_json
    if hasattr(anchor_object, "body_json") and anchor_object.body_json:
        return anchor_object.body_json

    # Other types: try to inject from their body field via adapter
    model_name = anchor_object.__class__.__name__.lower()
    try:
        adapter = get_adapter(model_name)
        if hasattr(anchor_object, "description"):
            return adapter.inject_body(anchor_object.description)
        if hasattr(anchor_object, "body"):
            return adapter.inject_body(anchor_object.body)
        if hasattr(anchor_object, "body_text"):
            return adapter.inject_body(anchor_object.body_text)
    except ValueError:
        pass

    # Fallback: empty TipTap doc
    return {"type": "doc", "content": [{"type": "paragraph"}]}


@transaction.atomic
def add_session_item(session, artifact_object):
    """
    Add an artifact to a Work Session with the next sequence number.
    Returns the created WorkSessionItem.
    """
    ct = ContentType.objects.get_for_model(artifact_object)

    # Get next sequence number
    max_seq = session.items.aggregate(max_seq=Max("sequence"))["max_seq"]
    next_seq = (max_seq or 0) + 1

    item = WorkSessionItem.objects.create(
        session=session,
        content_type=ct,
        object_id=artifact_object.pk,
        sequence=next_seq,
    )

    return item


@transaction.atomic
def remove_session_item(session, item_id):
    """
    Soft-delete a WorkSessionItem (set deleted_at).
    """
    item = session.items.get(pk=item_id)
    item.deleted_at = timezone.now()
    item.save(update_fields=["deleted_at", "updated_at"])
    return item


def save_surface_document(session, body_json, client_session_id=""):
    """
    Update the surface document body_json (autosave endpoint).
    Increments auto_save_count atomically.
    """
    surface = session.surface_document
    if surface is None:
        raise ValueError("Session has no surface document")

    surface.body_json = body_json
    surface.client_session_id = client_session_id
    surface.save(update_fields=["body_json", "client_session_id", "updated_at"])

    # Atomic increment
    WritingSurfaceDocument.objects.filter(pk=surface.pk).update(
        auto_save_count=F("auto_save_count") + 1
    )


@transaction.atomic
def checkpoint_extraction(session):
    """
    Walk the surface document's body_json for segmentBoundary nodes,
    derive segments, run body adapters, and update artifact draft state.

    Returns list of (artifact_type, artifact_id) tuples that were extracted.
    """
    surface = session.surface_document
    if surface is None or not surface.body_json:
        return []

    doc = surface.body_json
    content = doc.get("content", [])
    if not content:
        return []

    # Parse segments from boundary nodes
    segments = _parse_segments(content, session)

    # Extract and apply each segment
    extracted = []
    for segment in segments:
        artifact_type = segment["artifact_type"]
        artifact_id = segment["artifact_id"]
        is_anchor = segment["is_anchor"]
        nodes = segment["nodes"]

        if not nodes:
            continue

        try:
            adapter = get_adapter(artifact_type)
        except ValueError:
            continue

        # Extract body from TipTap nodes
        body = adapter.extract_body(nodes)

        # Apply to artifact
        if is_anchor:
            _apply_to_anchor(session, adapter, body)
        else:
            _apply_to_emitted(artifact_type, artifact_id, adapter, body, session.owner)

        extracted.append((artifact_type, artifact_id))

    return extracted


def _parse_segments(content_nodes, session):
    """
    Parse TipTap content nodes into segments based on segmentBoundary nodes.
    Merges multiple anchor segments in order.

    Returns list of segment dicts:
    {
        "artifact_type": str,
        "artifact_id": str,
        "is_anchor": bool,
        "nodes": list[dict],
    }
    """
    anchor_type = session.anchor_content_type.model
    anchor_id = str(session.anchor_object_id)

    segments = []
    current_segment = {
        "artifact_type": anchor_type,
        "artifact_id": anchor_id,
        "is_anchor": True,
        "nodes": [],
    }

    for node in content_nodes:
        if node.get("type") == "segmentBoundary":
            # Close current segment
            if current_segment["nodes"]:
                segments.append(current_segment)

            attrs = node.get("attrs", {})
            is_return = attrs.get("isAnchorReturn", False)

            if is_return:
                current_segment = {
                    "artifact_type": anchor_type,
                    "artifact_id": anchor_id,
                    "is_anchor": True,
                    "nodes": [],
                }
            else:
                current_segment = {
                    "artifact_type": attrs.get("artifactType", ""),
                    "artifact_id": attrs.get("artifactId", ""),
                    "is_anchor": False,
                    "nodes": [],
                }
        else:
            current_segment["nodes"].append(node)

    # Close final segment
    if current_segment["nodes"]:
        segments.append(current_segment)

    # Merge anchor segments in order
    return _merge_anchor_segments(segments, anchor_type, anchor_id)


def _merge_anchor_segments(segments, anchor_type, anchor_id):
    """
    Merge multiple anchor segments into one (preserving order).
    Non-anchor segments remain separate.
    """
    anchor_nodes = []
    result = []
    anchor_placed = False

    for seg in segments:
        if seg["is_anchor"]:
            anchor_nodes.extend(seg["nodes"])
            if not anchor_placed:
                # Mark position for the merged anchor segment
                anchor_placed = True
                result.append(None)  # placeholder
        else:
            result.append(seg)

    # Replace placeholder with merged anchor
    merged_anchor = {
        "artifact_type": anchor_type,
        "artifact_id": anchor_id,
        "is_anchor": True,
        "nodes": anchor_nodes,
    }

    return [merged_anchor if s is None else s for s in result] if anchor_placed else result


def _apply_to_anchor(session, adapter, body):
    """Apply extracted body to the anchor artifact."""
    anchor = session.anchor
    if anchor is None:
        return

    # For WritingPiece anchors, upsert WorkingDocument
    if hasattr(anchor, "working_copies"):
        from writing.models import WorkingDocument

        wc, created = WorkingDocument.objects.get_or_create(
            piece=anchor,
            user=session.owner,
        )
        wc.body_json = body
        wc.save(update_fields=["body_json", "updated_at"])
    else:
        adapter.apply_to_artifact(anchor, body)


def _apply_to_emitted(artifact_type, artifact_id, adapter, body, owner):
    """Apply extracted body to an emitted (non-anchor) artifact."""
    ct = ContentType.objects.filter(model=artifact_type).first()
    if ct is None:
        return

    model_class = ct.model_class()
    if model_class is None:
        return

    try:
        artifact = model_class.objects.get(pk=artifact_id)
    except model_class.DoesNotExist:
        return

    # For WritingPiece, upsert WorkingDocument
    if hasattr(artifact, "working_copies"):
        from writing.models import WorkingDocument

        wc, created = WorkingDocument.objects.get_or_create(
            piece=artifact,
            user=owner,
        )
        wc.body_json = body
        wc.save(update_fields=["body_json", "updated_at"])
    else:
        adapter.apply_to_artifact(artifact, body)


@transaction.atomic
def close_session(session):
    """
    Close a Work Session. Runs final checkpoint extraction and sets ended_at.
    """
    checkpoint_extraction(session)
    session.ended_at = timezone.now()
    session.save(update_fields=["ended_at", "updated_at"])
    return session


@transaction.atomic
def merge_artifact(session, source_object, target_object, merged_by):
    """
    Record an artifact merge (boundary deletion).
    Soft-deletes the source artifact and removes its WorkSessionItem.
    """
    source_ct = ContentType.objects.get_for_model(source_object)
    target_ct = ContentType.objects.get_for_model(target_object)

    record = ArtifactMergeRecord.objects.create(
        source_content_type=source_ct,
        source_object_id=source_object.pk,
        target_content_type=target_ct,
        target_object_id=target_object.pk,
        merged_by=merged_by,
    )

    # Soft-delete source artifact
    source_object.deleted_at = timezone.now()
    source_object.save(update_fields=["deleted_at", "updated_at"])

    # Remove from session items
    session.items.filter(
        content_type=source_ct,
        object_id=source_object.pk,
    ).update(deleted_at=timezone.now())

    return record
