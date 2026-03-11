import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel


class WritingSurfaceDocument(BaseModel):
    """
    The composed multi-artifact writing stream for a Work Session.
    Contains the full TipTap document including segmentBoundary nodes.

    This is the draft store for composed (multi-artifact) editing sessions.
    Standalone single-artifact editing uses WorkingDocument instead.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    body_json = models.JSONField(
        default=dict,
        help_text="Full TipTap document with segmentBoundary nodes",
    )

    # Autosave tracking
    last_saved_at = models.DateTimeField(auto_now=True)
    auto_save_count = models.PositiveIntegerField(default=0)
    client_session_id = models.CharField(max_length=64, blank=True, default="")

    class Meta(BaseModel.Meta):
        verbose_name = "Writing Surface Document"
        verbose_name_plural = "Writing Surface Documents"

    def __str__(self):
        return f"SurfaceDoc {self.id} (saves: {self.auto_save_count})"


class WorkSession(BaseModel):
    """
    Records a writing session that may produce multiple artifacts.
    Auto-created when the writer first uses /new during editing.

    v1 supports composed sessions only (Pattern B — writing stream).
    Pattern A (gathered sessions from Draft Room) deferred to later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="work_sessions",
    )

    # Anchor artifact (polymorphic — could be WritingPiece, Event, Course, etc.)
    anchor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    anchor_object_id = models.UUIDField()
    anchor = GenericForeignKey("anchor_content_type", "anchor_object_id")

    # Writing surface
    surface_document = models.OneToOneField(
        WritingSurfaceDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_session",
    )

    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Work Session"
        verbose_name_plural = "Work Sessions"
        indexes = [
            models.Index(fields=["owner", "-started_at"]),
        ]

    def __str__(self):
        status = "active" if self.ended_at is None else "ended"
        return f"WorkSession {self.id} ({status})"

    @property
    def is_active(self):
        return self.ended_at is None and self.deleted_at is None


class WorkSessionItem(BaseModel):
    """
    Records an artifact produced or referenced during a Work Session.
    Each /new command creates one of these.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        WorkSession,
        on_delete=models.CASCADE,
        related_name="items",
    )

    # Artifact (polymorphic)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    object_id = models.UUIDField()
    artifact = GenericForeignKey("content_type", "object_id")

    sequence = models.PositiveIntegerField()

    class Meta(BaseModel.Meta):
        ordering = ["sequence"]
        unique_together = [("session", "content_type", "object_id")]
        verbose_name = "Work Session Item"
        verbose_name_plural = "Work Session Items"

    def __str__(self):
        return f"Item #{self.sequence} ({self.content_type.model})"


class ArtifactMergeRecord(BaseModel):
    """
    Records when an emitted artifact is merged back into another artifact
    via boundary deletion in the writing stream.

    The source artifact is soft-deleted after merge.
    This table remains sparse — only actual merge events.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Source (the artifact being merged away)
    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    source_object_id = models.UUIDField()
    source = GenericForeignKey("source_content_type", "source_object_id")

    # Target (the artifact absorbing the content)
    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
    )
    target_object_id = models.UUIDField()
    target = GenericForeignKey("target_content_type", "target_object_id")

    merged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Artifact Merge Record"
        verbose_name_plural = "Artifact Merge Records"

    def __str__(self):
        return (
            f"Merge: {self.source_content_type.model} → "
            f"{self.target_content_type.model}"
        )
