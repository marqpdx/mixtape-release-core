from __future__ import annotations

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class StackroomSyncState(models.Model):
    """
    Minimal per-object ingest bookkeeping for universal Stackroom integration.

    The sync row belongs to a canonical application object via GenericForeignKey.
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

    MODE_LOCAL = "local"
    MODE_SHADOW = "shadow"
    MODE_REMOTE = "remote"
    MODE_CHOICES = [
        (MODE_LOCAL, "Local"),
        (MODE_SHADOW, "Shadow"),
        (MODE_REMOTE, "Remote"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")

    adapter_name = models.CharField(max_length=64, db_index=True)
    transport_mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_LOCAL)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)

    last_ingested_at = models.DateTimeField(null=True, blank=True)
    last_synced_hash = models.CharField(max_length=64, blank=True, default="")
    last_error = models.TextField(blank=True, default="")

    stackroom_library_id = models.UUIDField(null=True, blank=True)
    stackroom_source_file_id = models.UUIDField(null=True, blank=True)
    stackroom_artifact_id = models.UUIDField(null=True, blank=True)
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
