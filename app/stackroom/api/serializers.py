# stackroom/api/serializers.py

from __future__ import annotations

from rest_framework import serializers
from stackroom.models import (
    Library, SourceFile, IngestionRun, Artifact, Shard, Chunk, IngestionReceipt
)


class IngestionStartSerializer(serializers.Serializer):
    library_id = serializers.UUIDField()
    origin = serializers.CharField()
    path = serializers.CharField()
    filename = serializers.CharField()
    content_type = serializers.CharField(required=False, allow_blank=True)
    size_bytes = serializers.IntegerField(required=False, default=0)
    hash_sha256 = serializers.CharField()
    git_commit = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    source_url = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    ir_version = serializers.CharField(required=False, default="0.1")


class ArtifactCreateSerializer(serializers.Serializer):
    ingestion_run_id = serializers.UUIDField()
    source_file_id = serializers.UUIDField()
    artifact_uid = serializers.CharField()  # deterministic idempotency key from Stackroom
    artifact_type = serializers.CharField()
    format = serializers.CharField(required=False, default="text/plain")
    text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    storage_key = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    ir_version = serializers.CharField(required=False, default="0.1")


class ShardSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)  # allow server to accept client ids; else generate
    kind = serializers.CharField()
    level = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    text = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    order_index = serializers.IntegerField()
    parent_shard_id = serializers.UUIDField(required=False, allow_null=True)
    span = serializers.JSONField()


class ShardBulkSerializer(serializers.Serializer):
    ingestion_run_id = serializers.UUIDField()
    artifact_id = serializers.UUIDField()
    shards = ShardSerializer(many=True)


class ChunkSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    chunk_strategy = serializers.CharField(required=False, default="sliding_window")
    text = serializers.CharField()
    token_estimate = serializers.IntegerField(required=False, default=0)
    order_index = serializers.IntegerField()
    source_spans = serializers.JSONField()
    hash_sha256 = serializers.CharField()
    ir_version = serializers.CharField(required=False, default="0.1")
    embedding_id = serializers.CharField(required=False, allow_blank=True, default="")


class ChunkBulkSerializer(serializers.Serializer):
    ingestion_run_id = serializers.UUIDField()
    artifact_id = serializers.UUIDField()
    chunks = ChunkSerializer(many=True)


class IngestionCompleteSerializer(serializers.Serializer):
    ingestion_run_id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=["success", "partial", "failed"])
    errors = serializers.ListField(child=serializers.JSONField(), required=False, default=list)
    warnings = serializers.ListField(child=serializers.JSONField(), required=False, default=list)
    next_actions = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class FileUploadSerializer(serializers.Serializer):
    """Simplified file upload for direct user uploads"""
    library_id = serializers.UUIDField()
    file = serializers.FileField()


class FileUploadResponseSerializer(serializers.Serializer):
    """Response from file upload"""
    source_file_id = serializers.UUIDField()
    ingestion_run_id = serializers.UUIDField()
    filename = serializers.CharField()
    status = serializers.CharField()


class LibrarySerializer(serializers.Serializer):
    """Library metadata for frontend"""
    id = serializers.UUIDField()
    tenant_type = serializers.CharField()
    tenant_id = serializers.UUIDField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class LibraryCreateSerializer(serializers.Serializer):
    """Serializer for creating a new library"""
    tenant_type = serializers.CharField(max_length=20, help_text="Type of tenant: 'group' or 'user'")
    tenant_id = serializers.CharField(max_length=64, help_text="UUID or int-as-string")
    name = serializers.CharField(max_length=255, help_text="Library name")


class LibraryUpdateSerializer(serializers.Serializer):
    """Serializer for updating/renaming a library"""
    name = serializers.CharField(max_length=255, help_text="New library name")


# Retrieval API Serializers

class RetrieveRequestSerializer(serializers.Serializer):
    """Request serializer for semantic retrieval"""
    query = serializers.CharField(
        min_length=3,
        max_length=500,
        help_text="Query text to search for (3-500 characters)"
    )
    library_id = serializers.UUIDField(help_text="Library to search within")
    model_name = serializers.CharField(
        default="text-embedding-3-small",
        help_text="Embedding model name"
    )
    model_version = serializers.CharField(
        default="1",
        help_text="Embedding model version"
    )
    limit = serializers.IntegerField(
        default=10,
        min_value=1,
        max_value=100,
        help_text="Maximum number of results"
    )
    score_threshold = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum similarity score threshold"
    )
    artifact_types = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Filter by artifact types (e.g., ['normalized_markdown', 'extracted_text'])"
    )
    source_file_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_null=True,
        allow_empty=True,
        help_text="Filter by specific source file IDs"
    )


class ChunkResultSerializer(serializers.Serializer):
    """Serializer for chunk retrieval results"""
    chunk_id = serializers.UUIDField()
    text = serializers.CharField()
    score = serializers.FloatField()
    source_spans = serializers.JSONField()
    artifact_id = serializers.UUIDField()
    artifact_type = serializers.CharField()
    source_file_id = serializers.UUIDField()
    filename = serializers.CharField()
    path = serializers.CharField()


class RetrieveResponseSerializer(serializers.Serializer):
    """Response serializer for semantic retrieval"""
    query = serializers.CharField()
    results = ChunkResultSerializer(many=True)
    model = serializers.CharField()
    collection = serializers.CharField()
    timing = serializers.JSONField(required=False, help_text="Performance timing metrics")
