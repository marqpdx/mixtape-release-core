# mindmap/services/node_service.py

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from mindmap.models import MindMapEdge, MindMapNode
from mindmap.services.mindmap_service import bump_version

# Fields whose changes trigger a version bump (content/structure changes).
# Position, style, size, z_index, collapsed are visual-only — no bump.
VERSION_BUMP_FIELDS = {
    "title", "text", "primary_url", "backing_kind",
    "leaf", "leaf_id", "node_type", "meta",
}


def _apply_fields(instance, data, track_bump=True):
    """
    Apply data dict to instance fields. Returns (update_fields, needs_bump).
    Skips keys that don't exist on the model.
    """
    update_fields = []
    needs_bump = False
    for key, val in data.items():
        if hasattr(instance, key) and key not in ("id", "mind_map", "mind_map_id"):
            setattr(instance, key, val)
            update_fields.append(key)
            if track_bump and key in VERSION_BUMP_FIELDS:
                needs_bump = True
    return update_fields, needs_bump


@transaction.atomic
def create_node(*, mindmap, **data):
    """Create a single node and bump version."""
    node = MindMapNode(mind_map=mindmap, **data)
    node.save()
    bump_version(mindmap)
    return node


@transaction.atomic
def update_node(*, node, **data):
    """
    Update node fields. Only bumps version for content/structure changes.
    Position/style/size changes do not bump version.
    """
    update_fields, needs_bump = _apply_fields(node, data)
    if update_fields:
        update_fields.append("updated_at")
        node.save(update_fields=update_fields)
        if needs_bump:
            bump_version(node.mind_map)
    return node


@transaction.atomic
def delete_node(*, node):
    """
    Soft-delete a node and cascade soft-delete to connected edges.
    Bumps version.
    """
    now = timezone.now()
    node.deleted_at = now
    node.save(update_fields=["deleted_at", "updated_at"])
    # Cascade to connected edges
    MindMapEdge.objects.filter(
        Q(source_node=node) | Q(target_node=node),
        deleted_at__isnull=True,
    ).update(deleted_at=now)
    bump_version(node.mind_map)


@transaction.atomic
def bulk_upsert_nodes(*, mindmap, items):
    """
    Create or update nodes in bulk. Single version bump at the end.

    Each item is a dict. If 'id' is present, it's an update (partial — missing
    keys are left unchanged per spec Appendix A1). If 'id' is absent, it's a create.
    """
    results = []
    needs_bump = False

    for item in items:
        item = dict(item)  # shallow copy so we can pop
        node_id = item.pop("id", None)

        if node_id:
            # Update existing node
            node = MindMapNode.objects.filter(
                pk=node_id, mind_map=mindmap, deleted_at__isnull=True
            ).first()
            if not node:
                results.append({"id": str(node_id), "ok": False, "errors": ["Not found"]})
                continue

            update_fields, item_bumps = _apply_fields(node, item)
            if update_fields:
                update_fields.append("updated_at")
                node.save(update_fields=update_fields)
                if item_bumps:
                    needs_bump = True
            results.append({"id": str(node.pk), "ok": True, "errors": []})
        else:
            # Create new node
            node = MindMapNode(mind_map=mindmap, **item)
            node.save()
            needs_bump = True
            results.append({"id": str(node.pk), "ok": True, "errors": []})

    if needs_bump:
        version = bump_version(mindmap)
    else:
        version = mindmap.version

    return results, version


@transaction.atomic
def bulk_delete_nodes(*, mindmap, ids):
    """
    Soft-delete nodes and cascade to connected edges. Single version bump.
    """
    now = timezone.now()
    nodes_qs = MindMapNode.objects.filter(
        pk__in=ids, mind_map=mindmap, deleted_at__isnull=True
    )
    count = nodes_qs.update(deleted_at=now)

    # Cascade soft-delete to edges connected to any deleted node
    MindMapEdge.objects.filter(
        Q(source_node_id__in=ids) | Q(target_node_id__in=ids),
        mind_map=mindmap,
        deleted_at__isnull=True,
    ).update(deleted_at=now)

    version = mindmap.version
    if count > 0:
        version = bump_version(mindmap)

    return count, version


@transaction.atomic
def restore_node(*, node):
    """
    Restore a soft-deleted node and its connected edges (for future undo).
    """
    node.deleted_at = None
    node.save(update_fields=["deleted_at", "updated_at"])
    # Restore edges that were cascade-deleted with this node
    MindMapEdge.objects.filter(
        Q(source_node=node) | Q(target_node=node),
        deleted_at__isnull=False,
    ).update(deleted_at=None)
    bump_version(node.mind_map)
