import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


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
