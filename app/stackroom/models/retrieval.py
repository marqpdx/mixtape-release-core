# stackroom/models/retrieval.py
"""
Models for retrieval and query logging.
"""
from __future__ import annotations

import uuid
from django.db import models
from django.conf import settings

from .ir import TimeStamped, Library
from .embeddings import EmbeddingModel


class QueryLog(TimeStamped):
    """
    Minimal query log for observability and analytics.

    Records semantic retrieval queries for monitoring and debugging.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Scope
    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name="query_logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stackroom_queries"
    )

    # Query details (query text is hashed for privacy)
    query_hash = models.CharField(max_length=64, help_text="SHA256 hash of query text")
    query_length = models.IntegerField(help_text="Character length of original query")

    # Embedding model used
    embedding_model = models.ForeignKey(
        EmbeddingModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="query_logs"
    )

    # Request parameters
    limit = models.IntegerField(default=10)
    score_threshold = models.FloatField(null=True, blank=True)
    artifact_types = models.JSONField(null=True, blank=True, help_text="List of artifact types filtered")
    source_file_ids = models.JSONField(null=True, blank=True, help_text="List of source file IDs filtered")

    # Results
    result_count = models.IntegerField(default=0, help_text="Number of results returned")

    # Performance metrics (milliseconds)
    embed_ms = models.FloatField(null=True, blank=True, help_text="Time to embed query")
    qdrant_ms = models.FloatField(null=True, blank=True, help_text="Time for Qdrant search")
    resolve_ms = models.FloatField(null=True, blank=True, help_text="Time to resolve chunks from Django")
    total_ms = models.FloatField(null=True, blank=True, help_text="Total request time")

    # Error tracking
    error_code = models.CharField(max_length=64, null=True, blank=True)
    error_detail = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["library", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["embedding_model", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Query {self.id} on {self.library.name} at {self.created_at}"
