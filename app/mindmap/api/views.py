# mindmap/api/views.py

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from mindmap.models import MindMap, MindMapEdge, MindMapNode, MindMapNodeAttachment
from mindmap.services import edge_service, mindmap_service, node_service

from .serializers import (
    EdgeBulkUpsertItemSerializer,
    MindMapDetailSerializer,
    MindMapEdgeSerializer,
    MindMapListSerializer,
    MindMapNodeAttachmentSerializer,
    MindMapNodeSerializer,
    NodeBulkUpsertItemSerializer,
)


# ---- Helpers ----

def _get_user_ct():
    from django.contrib.auth import get_user_model
    return ContentType.objects.get_for_model(get_user_model())


def _get_mindmap_for_owner(request, mindmap_id):
    """Get a mindmap and verify the request user is the sponsor (owner)."""
    mindmap = get_object_or_404(MindMap, pk=mindmap_id, deleted_at__isnull=True)
    user_ct = _get_user_ct()
    if (
        mindmap.sponsor_content_type_id != user_ct.pk
        or str(mindmap.sponsor_object_id) != str(request.user.pk)
    ):
        raise PermissionDenied("Not the owner of this mindmap.")
    return mindmap


# ---- MindMap views ----

class MindMapListCreateView(generics.GenericAPIView):
    """GET: list user's mindmaps. POST: create a new mindmap."""
    serializer_class = MindMapListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user_ct = _get_user_ct()
        qs = MindMap.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=request.user.pk,
            deleted_at__isnull=True,
        ).order_by("-updated_at")
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        mindmap = mindmap_service.create_mindmap(
            sponsor=request.user,
            title=serializer.validated_data.get("title", "Untitled"),
            author=request.user,
            submitted_by=request.user,
        )
        return Response(
            MindMapListSerializer(mindmap).data,
            status=status.HTTP_201_CREATED,
        )


class MindMapDetailView(generics.GenericAPIView):
    """GET: mindmap detail with counts. PATCH: update mindmap fields."""
    serializer_class = MindMapDetailSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        mindmap = MindMap.objects.filter(pk=mindmap.pk).annotate(
            node_count=Count("nodes", filter=Q(nodes__deleted_at__isnull=True), distinct=True),
            edge_count=Count("edges", filter=Q(edges__deleted_at__isnull=True), distinct=True),
        ).first()
        return Response(MindMapDetailSerializer(mindmap).data)

    def patch(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        mindmap = mindmap_service.update_mindmap(mindmap=mindmap, **request.data)
        return Response({"ok": True})


# ---- Node views ----

class MindMapNodeListCreateView(generics.GenericAPIView):
    """GET: all nodes for a mindmap. POST: create a single node."""
    serializer_class = MindMapNodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        nodes = MindMapNode.objects.filter(
            mind_map=mindmap, deleted_at__isnull=True
        ).prefetch_related("attachments")
        serializer = self.get_serializer(nodes, many=True)
        return Response(serializer.data)

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = node_service.create_node(mindmap=mindmap, **serializer.validated_data)
        return Response(
            MindMapNodeSerializer(node).data,
            status=status.HTTP_201_CREATED,
        )


class MindMapNodeDetailView(generics.GenericAPIView):
    """PATCH: update a node. DELETE: soft-delete a node."""
    serializer_class = MindMapNodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_node(self, request, mindmap_id, node_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        node = get_object_or_404(
            MindMapNode, pk=node_id, mind_map=mindmap, deleted_at__isnull=True
        )
        return node

    def patch(self, request, mindmap_id, node_id):
        node = self._get_node(request, mindmap_id, node_id)
        node = node_service.update_node(node=node, **request.data)
        return Response(MindMapNodeSerializer(node).data)

    def delete(self, request, mindmap_id, node_id):
        node = self._get_node(request, mindmap_id, node_id)
        node_service.delete_node(node=node)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MindMapNodeBulkUpsertView(generics.GenericAPIView):
    """POST: bulk upsert nodes (Appendix A1)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        items = request.data.get("items", [])
        if not items:
            raise ValidationError({"items": "items list is required."})

        # Validate each item
        validated_items = []
        for item in items:
            ser = NodeBulkUpsertItemSerializer(data=item)
            ser.is_valid(raise_exception=True)
            validated_items.append(ser.validated_data)

        results, version = node_service.bulk_upsert_nodes(
            mindmap=mindmap, items=validated_items
        )
        return Response({
            "ok": True,
            "mindmap_id": str(mindmap.pk),
            "version": version,
            "results": results,
        })


class MindMapNodeBulkDeleteView(generics.GenericAPIView):
    """POST: bulk soft-delete nodes (Appendix A2)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        ids = request.data.get("ids", [])
        if not ids:
            raise ValidationError({"ids": "ids list is required."})

        count, version = node_service.bulk_delete_nodes(mindmap=mindmap, ids=ids)
        return Response({
            "ok": True,
            "deleted": count,
            "version": version,
        })


# ---- Edge views ----

class MindMapEdgeListCreateView(generics.GenericAPIView):
    """GET: all edges for a mindmap. POST: create a single edge."""
    serializer_class = MindMapEdgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        edges = MindMapEdge.objects.filter(
            mind_map=mindmap, deleted_at__isnull=True
        )
        serializer = self.get_serializer(edges, many=True)
        return Response(serializer.data)

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # validated_data["source_node"] / ["target_node"] are model instances (DRF FK resolution)
        source = serializer.validated_data["source_node"]
        target = serializer.validated_data["target_node"]

        # Verify both nodes belong to this mindmap and are not soft-deleted
        for label, node in [("source_node", source), ("target_node", target)]:
            if node.mind_map_id != mindmap.pk or node.deleted_at is not None:
                raise ValidationError({label: f"Node {node.pk} not found in this mindmap."})

        edge = edge_service.create_edge(
            mindmap=mindmap,
            source_node=source,
            target_node=target,
            edge_type=serializer.validated_data["edge_type"],
            label=serializer.validated_data.get("label"),
            directed=serializer.validated_data.get("directed", True),
            style=serializer.validated_data.get("style"),
            meta=serializer.validated_data.get("meta", {}),
        )
        return Response(
            MindMapEdgeSerializer(edge).data,
            status=status.HTTP_201_CREATED,
        )


class MindMapEdgeDetailView(generics.GenericAPIView):
    """PATCH: update an edge. DELETE: soft-delete an edge."""
    serializer_class = MindMapEdgeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_edge(self, request, mindmap_id, edge_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        edge = get_object_or_404(
            MindMapEdge, pk=edge_id, mind_map=mindmap, deleted_at__isnull=True
        )
        return edge

    def patch(self, request, mindmap_id, edge_id):
        edge = self._get_edge(request, mindmap_id, edge_id)
        edge = edge_service.update_edge(edge=edge, **request.data)
        return Response(MindMapEdgeSerializer(edge).data)

    def delete(self, request, mindmap_id, edge_id):
        edge = self._get_edge(request, mindmap_id, edge_id)
        edge_service.delete_edge(edge=edge)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MindMapEdgeBulkUpsertView(generics.GenericAPIView):
    """POST: bulk upsert edges (Appendix A3)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        items = request.data.get("items", [])
        if not items:
            raise ValidationError({"items": "items list is required."})

        validated_items = []
        for item in items:
            ser = EdgeBulkUpsertItemSerializer(data=item)
            ser.is_valid(raise_exception=True)
            validated_items.append(ser.validated_data)

        results, version = edge_service.bulk_upsert_edges(
            mindmap=mindmap, items=validated_items
        )
        return Response({
            "ok": True,
            "mindmap_id": str(mindmap.pk),
            "version": version,
            "results": results,
        })


class MindMapEdgeBulkDeleteView(generics.GenericAPIView):
    """POST: bulk soft-delete edges (Appendix A4)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, mindmap_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        ids = request.data.get("ids", [])
        if not ids:
            raise ValidationError({"ids": "ids list is required."})

        count, version = edge_service.bulk_delete_edges(mindmap=mindmap, ids=ids)
        return Response({
            "ok": True,
            "deleted": count,
            "version": version,
        })


# ---- Attachment views ----

class MindMapNodeAttachmentListCreateView(generics.GenericAPIView):
    """GET: list attachments for a node. POST: add attachment."""
    serializer_class = MindMapNodeAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_node(self, request, mindmap_id, node_id):
        mindmap = _get_mindmap_for_owner(request, mindmap_id)
        return get_object_or_404(
            MindMapNode, pk=node_id, mind_map=mindmap, deleted_at__isnull=True
        )

    def get(self, request, mindmap_id, node_id):
        node = self._get_node(request, mindmap_id, node_id)
        attachments = MindMapNodeAttachment.objects.filter(
            node=node, deleted_at__isnull=True
        )
        return Response(
            MindMapNodeAttachmentSerializer(attachments, many=True).data
        )

    def post(self, request, mindmap_id, node_id):
        node = self._get_node(request, mindmap_id, node_id)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = MindMapNodeAttachment.objects.create(
            node=node, **serializer.validated_data
        )
        # Attachment add bumps version
        from mindmap.services.mindmap_service import bump_version
        bump_version(node.mind_map)
        return Response(
            MindMapNodeAttachmentSerializer(attachment).data,
            status=status.HTTP_201_CREATED,
        )


class MindMapNodeAttachmentDetailView(generics.GenericAPIView):
    """PATCH: update attachment. DELETE: soft-delete attachment."""
    serializer_class = MindMapNodeAttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _get_attachment(self, request, mindmap_id, node_id, attachment_id):
        _get_mindmap_for_owner(request, mindmap_id)
        return get_object_or_404(
            MindMapNodeAttachment,
            pk=attachment_id,
            node_id=node_id,
            node__mind_map_id=mindmap_id,
            deleted_at__isnull=True,
        )

    def patch(self, request, mindmap_id, node_id, attachment_id):
        attachment = self._get_attachment(request, mindmap_id, node_id, attachment_id)
        serializer = self.get_serializer(attachment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Attachment edit bumps version
        from mindmap.services.mindmap_service import bump_version
        bump_version(attachment.node.mind_map)
        return Response(serializer.data)

    def delete(self, request, mindmap_id, node_id, attachment_id):
        attachment = self._get_attachment(request, mindmap_id, node_id, attachment_id)
        from django.utils import timezone
        attachment.deleted_at = timezone.now()
        attachment.save(update_fields=["deleted_at", "updated_at"])
        # Attachment remove bumps version
        from mindmap.services.mindmap_service import bump_version
        bump_version(attachment.node.mind_map)
        return Response(status=status.HTTP_204_NO_CONTENT)
