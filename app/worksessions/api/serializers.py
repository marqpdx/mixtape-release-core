from rest_framework import serializers

from worksessions.models import (
    ArtifactMergeRecord,
    WorkSession,
    WorkSessionItem,
    WritingSurfaceDocument,
)


class WritingSurfaceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = WritingSurfaceDocument
        fields = [
            "id",
            "body_json",
            "last_saved_at",
            "auto_save_count",
            "client_session_id",
        ]
        read_only_fields = ["id", "last_saved_at", "auto_save_count"]


class SurfaceDocumentSaveSerializer(serializers.Serializer):
    """Write-only serializer for autosave endpoint."""

    body_json = serializers.JSONField()
    client_session_id = serializers.CharField(
        max_length=64, required=False, default=""
    )


class WorkSessionItemSerializer(serializers.ModelSerializer):
    artifact_type = serializers.SerializerMethodField()
    artifact_title = serializers.SerializerMethodField()

    class Meta:
        model = WorkSessionItem
        fields = [
            "id",
            "content_type",
            "object_id",
            "sequence",
            "artifact_type",
            "artifact_title",
        ]
        read_only_fields = ["id", "sequence", "artifact_type", "artifact_title"]

    def get_artifact_type(self, obj):
        return obj.content_type.model if obj.content_type else None

    def get_artifact_title(self, obj):
        artifact = obj.artifact
        if artifact is None:
            return None
        return getattr(artifact, "title", str(artifact))


class WorkSessionItemCreateSerializer(serializers.Serializer):
    """Write-only serializer for adding items to a session."""

    content_type_model = serializers.CharField(
        help_text="Model name, e.g. 'writingpiece', 'event', 'course', 'seed'"
    )
    object_id = serializers.UUIDField()


class WorkSessionSerializer(serializers.ModelSerializer):
    items = WorkSessionItemSerializer(many=True, read_only=True)
    surface_document = WritingSurfaceDocumentSerializer(read_only=True)
    anchor_type = serializers.SerializerMethodField()

    class Meta:
        model = WorkSession
        fields = [
            "id",
            "owner",
            "anchor_content_type",
            "anchor_object_id",
            "anchor_type",
            "surface_document",
            "started_at",
            "ended_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "owner",
            "anchor_type",
            "surface_document",
            "started_at",
            "items",
        ]

    def get_anchor_type(self, obj):
        return obj.anchor_content_type.model if obj.anchor_content_type else None


class WorkSessionCreateSerializer(serializers.Serializer):
    """Write-only serializer for creating a session."""

    anchor_content_type_model = serializers.CharField(
        help_text="Model name, e.g. 'writingpiece'"
    )
    anchor_object_id = serializers.UUIDField()


class ArtifactMergeRecordSerializer(serializers.ModelSerializer):
    source_type = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()

    class Meta:
        model = ArtifactMergeRecord
        fields = [
            "id",
            "source_content_type",
            "source_object_id",
            "source_type",
            "target_content_type",
            "target_object_id",
            "target_type",
            "merged_by",
            "created_at",
        ]
        read_only_fields = fields

    def get_source_type(self, obj):
        return obj.source_content_type.model if obj.source_content_type else None

    def get_target_type(self, obj):
        return obj.target_content_type.model if obj.target_content_type else None
