from __future__ import annotations

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models

from fundamentals.bases import BaseModel


class CaptureSourceType(models.TextChoices):
    SCREENCAST       = "screencast",        "Screencast"
    BRIDGE_GATHERING = "bridge_gathering",  "Bridge Gathering"
    LIVESTREAM       = "livestream",        "Livestream"
    EXTERNAL_UPLOAD  = "external_upload",   "External Upload"


class CaptureStatus(models.TextChoices):
    UPLOADED     = "uploaded",     "Uploaded"
    TRANSCRIBING = "transcribing", "Transcribing"
    READY        = "ready",        "Ready"
    FAILED       = "failed",       "Failed"


class VisibilityScope(models.TextChoices):
    CIRCLE     = "circle",     "Circle"
    GROUP      = "group",      "Group"
    CROSSROADS = "crossroads", "Crossroads"


class Transcript(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # capture FK set via post-create update (avoids circular dep at model level)
    capture = models.ForeignKey(
        "media_capture.MediaCapture",
        on_delete=models.CASCADE,
        related_name="transcripts",
    )
    body_json = models.JSONField(default=list)
    raw_text = models.TextField(blank=True)
    stackroom_ingested_at = models.DateTimeField(null=True, blank=True)
    model_used = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Transcript({self.id}) for capture {self.capture_id}"


class MediaCapture(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(
        max_length=32,
        choices=CaptureSourceType.choices,
        default=CaptureSourceType.SCREENCAST,
    )
    title = models.CharField(max_length=255, blank=True)
    author = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="media_captures",
    )
    duration_seconds = models.IntegerField(null=True, blank=True)
    media_file = models.CharField(max_length=512, blank=True)
    has_video = models.BooleanField(default=True)
    transcript = models.OneToOneField(
        Transcript,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_for_capture",
    )
    status = models.CharField(
        max_length=32,
        choices=CaptureStatus.choices,
        default=CaptureStatus.UPLOADED,
    )
    intent_tags = ArrayField(
        models.CharField(max_length=32),
        default=list,
        blank=True,
    )
    # source_ref: nullable GFK — points to EventOccurrence for Bridge gatherings
    source_ref_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    source_ref_object_id = models.UUIDField(null=True, blank=True)
    source_ref = GenericForeignKey("source_ref_content_type", "source_ref_object_id")
    visibility_scope = models.CharField(
        max_length=32,
        choices=VisibilityScope.choices,
        default=VisibilityScope.CROSSROADS,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"MediaCapture({self.id}) — {self.title or self.source_type}"
