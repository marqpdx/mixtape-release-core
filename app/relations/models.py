# relations/models.py

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class RelationshipType(BaseModel):
    DOMAIN_STRUCTURAL = "structural"
    DOMAIN_EDITORIAL = "editorial"
    DOMAIN_SOCIAL = "social"
    DOMAIN_COMMONS = "commons"
    DOMAIN_INITIATIVE = "initiative"
    DOMAIN_SPATIAL = "spatial"

    DOMAIN_CHOICES = [
        (DOMAIN_STRUCTURAL, "Structural"),
        (DOMAIN_EDITORIAL, "Editorial"),
        (DOMAIN_SOCIAL, "Social"),
        (DOMAIN_COMMONS, "Commons"),
        (DOMAIN_INITIATIVE, "Initiative"),
        (DOMAIN_SPATIAL, "Spatial"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    inverse_label = models.CharField(max_length=100, blank=True, default="")
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES)
    is_directed = models.BooleanField(default=True)
    allows_position = models.BooleanField(default=False)
    allows_weight = models.BooleanField(default=False)
    uses_lifecycle = models.BooleanField(default=True)
    # Optional model constraints: list of "app_label.ModelName" strings
    valid_source_types = models.JSONField(default=list, blank=True)
    valid_target_types = models.JSONField(default=list, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["domain", "slug"]

    def __str__(self):
        return f"{self.domain}/{self.slug}"


class Relationship(BaseModel):
    LIFECYCLE_AUTHORED = "authored"
    LIFECYCLE_ACKNOWLEDGED = "acknowledged"
    LIFECYCLE_MUTUAL = "mutual"
    LIFECYCLE_CHOICES = [
        (LIFECYCLE_AUTHORED, "Authored"),
        (LIFECYCLE_ACKNOWLEDGED, "Acknowledged"),
        (LIFECYCLE_MUTUAL, "Mutual"),
    ]

    VISIBILITY_PUBLIC = "public"
    VISIBILITY_MEMBERS = "members"
    VISIBILITY_PRIVATE = "private"
    VISIBILITY_CHOICES = [
        (VISIBILITY_PUBLIC, "Public"),
        (VISIBILITY_MEMBERS, "Members"),
        (VISIBILITY_PRIVATE, "Private"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_ARCHIVED = "archived"
    STATUS_PENDING = "pending"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_ARCHIVED, "Archived"),
        (STATUS_PENDING, "Pending"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="outgoing_relationships",
    )
    source_object_id = models.UUIDField()
    source = GenericForeignKey("source_content_type", "source_object_id")

    target_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="incoming_relationships",
    )
    target_object_id = models.UUIDField()
    target = GenericForeignKey("target_content_type", "target_object_id")

    relationship_type = models.ForeignKey(
        RelationshipType,
        on_delete=models.PROTECT,
        related_name="relationships",
    )
    position = models.PositiveIntegerField(null=True, blank=True)
    weight = models.FloatField(null=True, blank=True)
    lifecycle = models.CharField(
        max_length=20, choices=LIFECYCLE_CHOICES, default=LIFECYCLE_AUTHORED
    )
    visibility = models.CharField(
        max_length=20, choices=VISIBILITY_CHOICES, default=VISIBILITY_PUBLIC
    )
    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_relationships",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )

    class Meta(BaseModel.Meta):
        ordering = ["position", "-created_at"]
        indexes = [
            models.Index(fields=["source_content_type", "source_object_id"]),
            models.Index(fields=["target_content_type", "target_object_id"]),
            models.Index(fields=["relationship_type", "status"]),
            models.Index(
                fields=["source_content_type", "source_object_id", "relationship_type"]
            ),
        ]
        constraints = [
            # One active record per (source, target, type) triple — also enforced at service layer
            models.UniqueConstraint(
                fields=[
                    "source_content_type",
                    "source_object_id",
                    "target_content_type",
                    "target_object_id",
                    "relationship_type",
                ],
                condition=models.Q(status="active"),
                name="relations_unique_active_relationship",
            )
        ]

    def __str__(self):
        return f"{self.source_content_type}/{self.source_object_id} —[{self.relationship_type_id}]→ {self.target_content_type}/{self.target_object_id}"


class RelationshipAnnotation(BaseModel):
    """Optional rich-text annotation on a Relationship record."""

    relationship = models.OneToOneField(
        Relationship,
        on_delete=models.CASCADE,
        related_name="annotation",
    )
    body = models.TextField(blank=True, default="")
    anchor_text = models.CharField(max_length=255, blank=True, default="")

    class Meta(BaseModel.Meta):
        pass

    def __str__(self):
        return f"Annotation on {self.relationship_id}"
