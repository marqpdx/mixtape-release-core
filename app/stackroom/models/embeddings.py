# stackroom/models/embeddings.py

from __future__ import annotations

from django.db import models
from django.utils import timezone


class EmbeddingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


class EmbeddingModel(models.Model):
    """
    Defines an embedding model *configuration identity* used by the system.

    This is NOT an ML artifact store. It is an immutable-ish registry row
    so we can reason about idempotency, backfills, and re-embedding policy.
    """

    # e.g. "text-embedding-3-large", "bge-large-en-v1.5"
    name = models.CharField(max_length=200)
    # e.g. "2025-01-15", "v1.5", "3.0"
    version = models.CharField(max_length=100)

    provider = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional: openai, huggingface, local, etc.",
    )
    dimensions = models.PositiveIntegerField()

    # Optional knobs (helpful later, safe now)
    normalize = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "version"],
                name="uniq_embedding_model_name_version",
            )
        ]

    def __str__(self) -> str:
        return f"{self.name}@{self.version}"


class ChunkEmbedding(models.Model):
    """
    A derived embedding record for a specific Chunk using a specific EmbeddingModel.

    Authority rules:
    - Chunk text + provenance are authoritative in Django IR models.
    - Qdrant stores vector + minimal payload (IDs only).
    - This model binds the two (and enables idempotency + audit).
    """

    # Adapt import path to your actual Chunk model
    chunk = models.ForeignKey(
        "stackroom.Chunk",
        on_delete=models.CASCADE,
        related_name="embeddings",
        db_index=True,
    )

    embedding_model = models.ForeignKey(
        EmbeddingModel,
        on_delete=models.PROTECT,
        related_name="chunk_embeddings",
        db_index=True,
    )

    # Library isolation: denormalize for enforcement + faster filtering
    library = models.ForeignKey(
        "stackroom.Library",
        on_delete=models.CASCADE,
        related_name="chunk_embeddings",
        db_index=True,
        help_text="Denormalized from chunk -> artifact -> source_file -> library for isolation guarantees.",
    )

    # Idempotency & drift detection
    embedded_text_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 hex digest of the exact text that was embedded.",
    )

    # Qdrant linkage (derived, replaceable)
    qdrant_collection = models.CharField(max_length=200)
    qdrant_point_id = models.CharField(
        max_length=100,
        help_text="Point ID in Qdrant (string/uuid).",
    )

    status = models.CharField(
        max_length=20,
        choices=EmbeddingStatus.choices,
        default=EmbeddingStatus.PENDING,
        db_index=True,
    )

    error_code = models.CharField(max_length=100, blank=True)
    error_detail = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "embedding_model", "embedded_text_hash"],
                name="uniq_chunk_embedding_identity",
            ),
        ]
        indexes = [
            models.Index(fields=["library", "embedding_model", "status"], name="idx_ce_lib_model_status"),
            models.Index(fields=["embedding_model", "status"], name="idx_ce_model_status"),
        ]


    def mark_complete(self) -> None:
        self.status = EmbeddingStatus.COMPLETE
        self.completed_at = timezone.now()

    def mark_failed(self, *, code: str = "", detail: str = "") -> None:
        self.status = EmbeddingStatus.FAILED
        self.error_code = code
        self.error_detail = detail
        self.completed_at = timezone.now()

    def __str__(self) -> str:
        return f"ChunkEmbedding(chunk={self.chunk_id}, model={self.embedding_model_id}, status={self.status})"
