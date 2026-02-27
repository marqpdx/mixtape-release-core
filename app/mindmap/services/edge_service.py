# mindmap/services/edge_service.py

from django.db import transaction
from django.utils import timezone

from mindmap.models import MindMapEdge
from mindmap.services.mindmap_service import bump_version

# Edge fields whose changes trigger a version bump (semantic changes).
# Style-only changes do not bump version.
VERSION_BUMP_FIELDS = {"edge_type", "label", "meta", "directed"}


def _apply_fields(edge, data):
    """Apply data dict to edge fields. Returns (update_fields, needs_bump)."""
    update_fields = []
    needs_bump = False
    for key, val in data.items():
        if hasattr(edge, key) and key not in (
            "id", "mind_map", "mind_map_id",
            "source_node", "source_node_id",
            "target_node", "target_node_id",
        ):
            setattr(edge, key, val)
            update_fields.append(key)
            if key in VERSION_BUMP_FIELDS:
                needs_bump = True
    return update_fields, needs_bump


@transaction.atomic
def create_edge(*, mindmap, source_node, target_node, edge_type, **kwargs):
    """Create a single edge and bump version."""
    edge = MindMapEdge(
        mind_map=mindmap,
        source_node=source_node,
        target_node=target_node,
        edge_type=edge_type,
        **kwargs,
    )
    edge.save()
    bump_version(mindmap)
    return edge


@transaction.atomic
def update_edge(*, edge, **data):
    """
    Update edge fields. Bumps version for semantic changes (type, label, meta).
    Style-only changes do not bump version.
    """
    update_fields, needs_bump = _apply_fields(edge, data)
    if update_fields:
        update_fields.append("updated_at")
        edge.save(update_fields=update_fields)
        if needs_bump:
            bump_version(edge.mind_map)
    return edge


@transaction.atomic
def delete_edge(*, edge):
    """Soft-delete an edge and bump version."""
    edge.deleted_at = timezone.now()
    edge.save(update_fields=["deleted_at", "updated_at"])
    bump_version(edge.mind_map)


@transaction.atomic
def bulk_upsert_edges(*, mindmap, items):
    """
    Create or update edges in bulk. Single version bump.
    Each item has optional 'id' (update) or no id (create with source/target/edge_type).
    """
    results = []
    needs_bump = False

    for item in items:
        item = dict(item)
        edge_id = item.pop("id", None)

        if edge_id:
            edge = MindMapEdge.objects.filter(
                pk=edge_id, mind_map=mindmap, deleted_at__isnull=True
            ).first()
            if not edge:
                results.append({"id": str(edge_id), "ok": False, "errors": ["Not found"]})
                continue

            update_fields, item_bumps = _apply_fields(edge, item)
            if update_fields:
                update_fields.append("updated_at")
                edge.save(update_fields=update_fields)
                if item_bumps:
                    needs_bump = True
            results.append({"id": str(edge.pk), "ok": True, "errors": []})
        else:
            # Create requires source_node_id, target_node_id, edge_type
            edge = MindMapEdge(mind_map=mindmap, **item)
            edge.save()
            needs_bump = True
            results.append({"id": str(edge.pk), "ok": True, "errors": []})

    if needs_bump:
        version = bump_version(mindmap)
    else:
        version = mindmap.version

    return results, version


@transaction.atomic
def bulk_delete_edges(*, mindmap, ids):
    """Soft-delete edges in bulk. Single version bump."""
    now = timezone.now()
    edges_qs = MindMapEdge.objects.filter(
        pk__in=ids, mind_map=mindmap, deleted_at__isnull=True
    )
    count = edges_qs.update(deleted_at=now)

    version = mindmap.version
    if count > 0:
        version = bump_version(mindmap)

    return count, version
