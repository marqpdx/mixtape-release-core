# stackroom/models/ir.py
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from fundamentals.models import BaseContent

# User = settings.AUTH_USER_MODEL


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Library(BaseContent):
    """
    Document library with polymorphic sponsorship.

    Inherits from BaseContent:
    - id (UUID)
    - title (the library name)
    - slug (auto-generated from title, unique per sponsor)
    - summary (short description)
    - body (detailed description/purpose)
    - sponsor (GenericFK to Group or User)
    - author, submitted_by
    - created_at, updated_at
    """

    class Meta(BaseContent.Meta):
        constraints = BaseContent.Meta.constraints + [
            # Unique library title per sponsor
            models.UniqueConstraint(
                fields=['sponsor_content_type', 'sponsor_object_id', 'title'],
                name='unique_library_title_per_sponsor'
            )
        ]
        verbose_name = "Library"
        verbose_name_plural = "Libraries"

    def __str__(self) -> str:
        sponsor_name = getattr(
            self.sponsor,
            'title',
            getattr(self.sponsor, 'display_name', str(self.sponsor))
        )
        return f"{sponsor_name} — {self.title}"


class SourceFile(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name="source_files")

    origin = models.CharField(max_length=20)  # "upload" | "git" | "external" | "audio"
    path = models.TextField()                # repo path or storage key
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    hash_sha256 = models.CharField(max_length=64)

    git_commit = models.CharField(max_length=64, null=True, blank=True)
    source_url = models.TextField(null=True, blank=True)

    # created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    ir_version = models.CharField(max_length=32, default="0.1")

    class Meta:
        constraints = [
            # Phase 0 contract: SourceFile identity = (library + hash)
            models.UniqueConstraint(fields=["library", "hash_sha256"], name="uniq_sourcefile_library_hash"),
        ]


class IngestionRun(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name="ingestion_runs")

    status = models.CharField(max_length=20, default="pending")  # pending|running|success|partial|failed
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # optional counters (denormalized convenience)
    artifacts_created = models.IntegerField(default=0)
    shards_extracted = models.IntegerField(default=0)
    chunks_indexed = models.IntegerField(default=0)

    # store errors/warnings here or in Receipt; keeping simple:
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"


class Artifact(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name="artifacts")

    artifact_uid = models.CharField(max_length=128)

    artifact_type = models.CharField(max_length=40)  # extracted_text | normalized_markdown | transcript_text | ...
    format = models.CharField(max_length=64, default="text/plain")
    text = models.TextField(null=True, blank=True)          # ok for Phase 1
    storage_key = models.TextField(null=True, blank=True)   # later

    ir_version = models.CharField(max_length=32, default="0.1")

    class Meta:
        indexes = [
            models.Index(fields=["source_file", "artifact_type"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_file", "artifact_uid"], name="uniq_artifact_uid_per_source"),
        ]


class Shard(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="shards")

    kind = models.CharField(max_length=40)  # heading|paragraph|list|table|code|...
    level = models.IntegerField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    text = models.TextField(null=True, blank=True)

    order_index = models.IntegerField()

    parent_shard = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    # provenance span
    span = models.JSONField(default=dict)  # {char_start, char_end, line_start?, page_start?, ...}

    class Meta:
        indexes = [
            models.Index(fields=["artifact", "order_index"]),
        ]


class Chunk(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="chunks")

    chunk_strategy = models.CharField(max_length=40, default="sliding_window")
    text = models.TextField()

    token_estimate = models.IntegerField(default=0)
    order_index = models.IntegerField()

    source_spans = models.JSONField(default=list)  # locked contract structure
    hash_sha256 = models.CharField(max_length=64)
    ir_version = models.CharField(max_length=32, default="0.1")

    # link to vector store point id (string; usually chunk UUID)
    embedding_id = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        constraints = [
            # Phase 0 contract: Chunk identity = (artifact + strategy + hash + ir_version)
            models.UniqueConstraint(
                fields=["artifact", "chunk_strategy", "hash_sha256", "ir_version"],
                name="uniq_chunk_identity",
            )
        ]
        indexes = [
            models.Index(fields=["artifact", "order_index"]),
        ]


class IngestionReceipt(TimeStamped):
    """
    Append-only receipts per run.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(IngestionRun, on_delete=models.CASCADE, related_name="receipts")

    status = models.CharField(max_length=20)  # success|partial|failed
    payload = models.JSONField(default=dict)

    class Meta:
        indexes = [models.Index(fields=["run", "created_at"])]
from django.db import models

# Create your models here.
