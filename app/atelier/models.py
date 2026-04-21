import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class WritingMarkerOccurrence(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_AFFIRMED = "affirmed"
    STATUS_DISMISSED = "dismissed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_AFFIRMED, "Affirmed"),
        (STATUS_DISMISSED, "Dismissed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    piece = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="marker_occurrences",
    )

    # raw capture from piece body
    raw_marker = models.TextField()
    raw_name = models.CharField(max_length=100)
    char_offset = models.IntegerField()

    # lifecycle
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    affirmed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    # writer-provided shape at affirmation
    label = models.CharField(max_length=500, blank=True, default="")
    body = models.TextField(blank=True, default="")

    # sponsor (User or Group — inferred from piece ownership)
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sponsored_marker_occurrences",
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    class Meta:
        ordering = ["char_offset"]
        indexes = [
            models.Index(fields=["piece", "status"]),
            models.Index(fields=["piece", "raw_name"]),
        ]

    def __str__(self):
        return f"/{self.raw_name} @ {self.char_offset} ({self.status})"


class ArtifactRelation(BaseModel):
    VERB_CHOICES = [
        ("mentions", "Mentions"),
        ("suggests", "Suggests"),
        ("recommends", "Recommends"),
        ("in_conversation_with", "In Conversation With"),
        ("extends", "Extends"),
        ("part_of", "Part Of"),
    ]

    STATUS_CHOICES = [
        ("authored", "Authored"),
        ("acknowledged", "Acknowledged"),
        ("mutual", "Mutual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="outgoing_relations",
    )
    source_object_id = models.UUIDField()
    source = GenericForeignKey("source_content_type", "source_object_id")

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="incoming_relations",
    )
    target_object_id = models.UUIDField()
    target = GenericForeignKey("target_content_type", "target_object_id")

    verb = models.CharField(max_length=30, choices=VERB_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="authored")

    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_relations",
    )

    note = models.TextField(blank=True, default="")
    visibility = models.CharField(max_length=20, default="public")

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_relations",
    )
    mutual_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [
            (
                "source_content_type",
                "source_object_id",
                "target_content_type",
                "target_object_id",
                "verb",
            )
        ]

    def __str__(self):
        return f"{self.source_object_id} —[{self.verb}]→ {self.target_object_id}"
