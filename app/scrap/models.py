# scrap/models.py
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Index

from fundamentals.bases import BaseModel


class IntentTag(models.TextChoices):
    REMINDER  = "reminder",  "Reminder"
    RECIPE    = "recipe",    "Recipe"
    CONTACT   = "contact",   "Contact"
    REFERENCE = "reference", "Reference"
    LIST      = "list",      "List"
    IDEA      = "idea",      "Idea"
    LINK      = "link",      "Link"
    QUESTION  = "question",  "Question"
    NOTE      = "note",      "Note"


class ScrapStatus(models.TextChoices):
    RAW      = "raw",      "Raw"
    REVIEWED = "reviewed", "Reviewed"
    PROMOTED = "promoted", "Promoted"
    ARCHIVED = "archived", "Archived"


class RemindStatus(models.TextChoices):
    PENDING   = "pending",   "Pending"
    SNOOZED   = "snoozed",   "Snoozed"
    DISMISSED = "dismissed", "Dismissed"


class Scrap(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Ownership — polymorphic: UserProfile or Group
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    owner_object_id = models.UUIDField()
    owner = GenericForeignKey("content_type", "owner_object_id")

    # Context — initiative this scrap lives in (nullable for personal scraps)
    initiative = models.ForeignKey(
        "initiatives.Initiative",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scraps",
    )

    # Associated ApertureLogEntry (nullable — populated when /scrap runs inside initiative)
    aperture_log_entry = models.ForeignKey(
        "initiatives.ApertureLogEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="scraps",
    )

    # Content
    body = models.TextField()
    intent_tag = models.CharField(max_length=32, choices=IntentTag.choices, default=IntentTag.NOTE)
    labels = ArrayField(
        models.CharField(max_length=64),
        default=list,
        blank=True,
        help_text="Max 10 labels, 64 chars each.",
    )
    metadata = models.JSONField(default=dict, blank=True)

    # Reminder facet (nullable — any Scrap can carry reminder behavior)
    remind_at = models.DateTimeField(null=True, blank=True)
    remind_recurrence = models.CharField(max_length=32, blank=True)
    remind_status = models.CharField(
        max_length=16,
        choices=RemindStatus.choices,
        null=True,
        blank=True,
    )

    # Lifecycle
    status = models.CharField(
        max_length=16,
        choices=ScrapStatus.choices,
        default=ScrapStatus.RAW,
    )

    # Promotion tracking
    promoted_to_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="promoted_from_scraps",
    )
    promoted_to_object_id = models.UUIDField(null=True, blank=True)
    promoted_to = GenericForeignKey("promoted_to_content_type", "promoted_to_object_id")

    # Misfit logging
    intent_tag_misfit = models.BooleanField(default=False)
    intent_tag_misfit_note = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            Index(fields=["intent_tag"]),
            Index(fields=["status"]),
            Index(fields=["content_type", "owner_object_id", "status"]),
            Index(fields=["remind_at", "remind_status"]),
        ]

    def __str__(self):
        return f"Scrap({self.intent_tag!r}, {self.body[:40]!r})"
