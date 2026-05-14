# inkwell/models.py

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from inkwell.config.constants import (
    DEFAULT_INGESTION_STATUS,
    INGESTION_STATUS_CHOICES,
    SYNOPSIS_STATUS_CHOICES,
)


class LLMBaseModel(models.Model):
    class Meta:
        abstract = True


class LLMSession(LLMBaseModel):
    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    summary = models.TextField()

    def __str__(self):
        return f"Session {self.session_id}"


class LLMMessage(LLMBaseModel):
    session = models.ForeignKey(LLMSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=[("user", "User"), ("ai", "AI")])
    text = models.TextField()
    markdown_text = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role.upper()} @ {self.timestamp.strftime('%H:%M:%S')}"


class StartupLog(models.Model):
    key = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="started")  # e.g. started, success, error
    message = models.TextField(blank=True)

    def __str__(self):
        return f"{self.key} — {self.status} at {self.completed_at or self.started_at}"


class SuggestedAsset(models.Model):
    source_id = models.CharField(max_length=64, null=True, blank=True)  # e.g. Gutenberg ID, DOI
    source = models.CharField(max_length=64, default="gutenberg")  # e.g. 'gutenberg', 'manual', 'pdf'
    asset_type = models.CharField(max_length=32, default="book")  # e.g. 'book', 'pdf', 'html'

    title = models.CharField(max_length=512, null=True, blank=True)
    author = models.CharField(max_length=512, null=True, blank=True)
    subject_tags = models.JSONField(default=list, blank=True)

    notes = models.TextField(null=True, blank=True)

    cover_url = models.URLField(null=True, blank=True)
    source_url = models.URLField(null=True, blank=True)

    retrieved = models.BooleanField(default=False)
    retrieved_at = models.DateTimeField(null=True, blank=True)

    approved = models.BooleanField(default=False)
    synopsis = models.TextField(null=True, blank=True)
    synopsis_status = models.CharField(
        max_length=16,
        choices=SYNOPSIS_STATUS_CHOICES,
        default="pending"
    )

    score = models.IntegerField(null=True, blank=True)

    suggested_at = models.DateTimeField(auto_now_add=True)

    ingestion_status = models.CharField(
        max_length=32,
        choices=INGESTION_STATUS_CHOICES,
        default=DEFAULT_INGESTION_STATUS,
    )
    ingestion_started_at = models.DateTimeField(null=True, blank=True)
    ingestion_completed_at = models.DateTimeField(null=True, blank=True)

    ingested = models.BooleanField(default=False)

    file_path = models.CharField(max_length=1024, null=True, blank=True)  # local file path if applicable

    @property
    def status(self):
        if DeclinedAsset.objects.filter(suggested_asset=self).exists():
            return "declined"
        if DeletedAsset.objects.filter(suggested_asset=self).exists():
            return "deleted"
        if self.approved:
            return "approved"
        if self.retrieved:
            return "in_process"
        return "suggested"


    def __str__(self):
        return self.title or f"Suggested Asset #{self.id}"


class SuggestedGutenbergInfo(models.Model):
    asset = models.OneToOneField("SuggestedAsset", on_delete=models.CASCADE, related_name="gutenberg_info")
    text_url = models.URLField(null=True, blank=True)
    gutenberg_id = models.PositiveIntegerField()
    version = models.CharField(max_length=50, null=True, blank=True)  # if relevant


class DeclinedAsset(models.Model):
    suggested_asset = models.OneToOneField(SuggestedAsset, on_delete=models.CASCADE, related_name="declined_asset")
    reason = models.TextField(null=True, blank=True)
    declined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Declined: {self.suggested_asset.title or self.suggested_asset.id}"


class ProtoAgentTask(models.Model):
    keyword_list = models.JSONField()
    books_per_agent = models.IntegerField(default=10)
    launched_at = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)


class IngestedAsset(models.Model):
    suggested_asset = models.OneToOneField("SuggestedAsset", on_delete=models.CASCADE)

    ingested_at = models.DateTimeField(auto_now_add=True)
    node_count = models.IntegerField(null=True, blank=True)
    token_count = models.IntegerField(null=True, blank=True)
    embedding_model = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Ingested: {self.suggested_asset.title or self.suggested_asset.id}"


class IngestedFile(models.Model):
    asset = models.ForeignKey(
        "IngestedAsset",
        on_delete=models.CASCADE,
        related_name="file_info"
    )

    filehash = models.CharField(max_length=128)
    filepath = models.CharField(max_length=1024)
    file_type = models.CharField(
        max_length=16,
        choices=[("txt", "Text"), ("pdf", "PDF")],
        default="txt"
    )
    collection_name = models.CharField(max_length=255)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("filehash", "collection_name")
        indexes = [
            models.Index(fields=["filehash", "collection_name"]),
        ]

    def __str__(self):
        return f"{self.filepath} ({self.file_type})"


class IngestedWebpage(models.Model):
    asset = models.ForeignKey(
        "IngestedAsset",
        on_delete=models.CASCADE,
        related_name="webpage_info"
    )

    url = models.URLField()
    title = models.CharField(max_length=512, null=True, blank=True)
    raw_html_path = models.CharField(max_length=1024, null=True, blank=True)
    extracted_text_path = models.CharField(max_length=1024, null=True, blank=True)
    scraped_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or self.url


class DeletedAsset(models.Model):
    suggested_asset = models.OneToOneField(
        SuggestedAsset,
        on_delete=models.SET_NULL,
        null=True,
        related_name="deleted_asset")
    deleted_title = models.CharField(max_length=255, null=True, blank=True)
    deleted_author = models.CharField(max_length=255, null=True, blank=True)
    reason = models.TextField(null=True, blank=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Deleted: {self.suggested_asset.title or self.suggested_asset.id}"


class DeletedGutenbergInfo(models.Model):
    deleted_asset = models.OneToOneField("DeletedAsset", on_delete=models.CASCADE, related_name="gutenberg_info")
    gutenberg_id = models.PositiveIntegerField()




class BlacklistedTitle(models.Model):
    loose_title = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)  # ← Add this
    reason = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.loose_title


class StackroomSyncState(models.Model):
    """
    Per-object bookkeeping for Django → Stackroom HTTP ingest.

    One row per (content object, adapter_name) pair. Tracks the last synced
    hash and the Stackroom source_file_id so updates can target the same record.
    """

    STATUS_PENDING = "pending"
    STATUS_SYNCED = "synced"
    STATUS_FAILED = "failed"
    STATUS_DEACTIVATED = "deactivated"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SYNCED, "Synced"),
        (STATUS_FAILED, "Failed"),
        (STATUS_DEACTIVATED, "Deactivated"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    adapter_name = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )

    last_ingested_at = models.DateTimeField(null=True, blank=True)
    last_synced_hash = models.CharField(max_length=64, blank=True, default="")
    last_error = models.TextField(blank=True, default="")

    stackroom_library_id = models.UUIDField(null=True, blank=True)
    stackroom_source_file_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["adapter_name", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "adapter_name"],
                name="uniq_stackroom_sync_state_object_adapter",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.adapter_name}:{self.content_type_id}:{self.object_id} ({self.status})"
