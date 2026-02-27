# mindmap/api/serializers.py

from rest_framework import serializers

from mindmap.models import MindMap, MindMapEdge, MindMapNode, MindMapNodeAttachment
from utils.shared.contenttypes import resolve_content_type


# ---- Attachment ----

class MindMapNodeAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MindMapNodeAttachment
        fields = [
            "id", "kind", "title", "url", "asset", "mime_type",
            "sort_order", "meta", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# ---- Node ----

class MindMapNodeSerializer(serializers.ModelSerializer):
    attachments = MindMapNodeAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = MindMapNode
        fields = [
            "id", "node_type", "pos_x", "pos_y", "width", "height",
            "z_index", "collapsed", "style", "backing_kind", "leaf",
            "title", "text", "primary_url", "meta", "attachments",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ---- Edge ----

class MindMapEdgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MindMapEdge
        fields = [
            "id", "source_node", "target_node", "edge_type", "label",
            "directed", "style", "meta", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ---- MindMap ----

class MindMapListSerializer(serializers.ModelSerializer):
    sponsor_content_type = serializers.CharField(write_only=True, required=False)
    sponsor_object_id = serializers.UUIDField(write_only=True, required=False)

    class Meta:
        model = MindMap
        fields = [
            "id", "title", "slug", "status", "version", "share_mode",
            "created_at", "updated_at",
            "sponsor_content_type", "sponsor_object_id",
        ]
        read_only_fields = [
            "id", "slug", "version", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        data = super().validate(attrs)
        raw_ct = self.initial_data.get("sponsor_content_type")
        if raw_ct:
            data["sponsor_content_type"] = resolve_content_type(raw_ct)
        return data


class MindMapDetailSerializer(serializers.ModelSerializer):
    node_count = serializers.IntegerField(read_only=True, default=0)
    edge_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = MindMap
        fields = [
            "id", "title", "slug", "summary", "status", "viewport",
            "version", "share_mode", "share_token",
            "node_count", "edge_count",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "slug", "version", "node_count", "edge_count",
            "created_at", "updated_at",
        ]


# ---- Bulk operation serializers ----

class NodeBulkUpsertItemSerializer(serializers.Serializer):
    """Validates a single item in a bulk upsert payload (Appendix A1)."""
    id = serializers.IntegerField(required=False, allow_null=True)
    node_type = serializers.CharField(max_length=32, required=False)
    pos_x = serializers.FloatField(required=False)
    pos_y = serializers.FloatField(required=False)
    width = serializers.FloatField(required=False, allow_null=True)
    height = serializers.FloatField(required=False, allow_null=True)
    z_index = serializers.IntegerField(required=False, allow_null=True)
    collapsed = serializers.BooleanField(required=False)
    style = serializers.JSONField(required=False, allow_null=True)
    backing_kind = serializers.ChoiceField(
        choices=MindMapNode.BackingKind.choices, required=False
    )
    leaf = serializers.UUIDField(required=False, allow_null=True, source="leaf_id")
    title = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    primary_url = serializers.URLField(required=False, allow_null=True, allow_blank=True)
    meta = serializers.JSONField(required=False)

    def validate(self, attrs):
        """On create (no id), node_type is required."""
        if not attrs.get("id") and not attrs.get("node_type"):
            raise serializers.ValidationError(
                {"node_type": "node_type is required when creating a new node."}
            )
        return attrs


class EdgeBulkUpsertItemSerializer(serializers.Serializer):
    """Validates a single item in a bulk edge upsert payload (Appendix A3)."""
    id = serializers.IntegerField(required=False, allow_null=True)
    source_node = serializers.IntegerField(required=False, source="source_node_id")
    target_node = serializers.IntegerField(required=False, source="target_node_id")
    edge_type = serializers.CharField(max_length=32, required=False)
    label = serializers.CharField(max_length=255, required=False, allow_null=True, allow_blank=True)
    directed = serializers.BooleanField(required=False)
    style = serializers.JSONField(required=False, allow_null=True)
    meta = serializers.JSONField(required=False)

    def validate(self, attrs):
        """On create (no id), source, target, edge_type are required."""
        if not attrs.get("id"):
            for field in ("source_node_id", "target_node_id", "edge_type"):
                if not attrs.get(field):
                    raise serializers.ValidationError(
                        {field: f"{field} is required when creating a new edge."}
                    )
        return attrs
