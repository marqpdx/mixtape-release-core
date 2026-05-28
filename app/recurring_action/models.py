# recurring_action/models.py
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class RecurrencePattern(models.TextChoices):
    DAILY    = "daily",    "Daily"
    WEEKLY   = "weekly",   "Weekly"
    BIWEEKLY = "biweekly", "Every two weeks"
    MONTHLY  = "monthly",  "Monthly"


class RecurringAction(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Ownership — polymorphic: UserProfile or Group
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    owner_object_id = models.UUIDField()
    owner = GenericForeignKey("content_type", "owner_object_id")

    # Identity
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Recurrence
    recurrence_rule = models.CharField(max_length=64, choices=RecurrencePattern.choices)
    next_due_at = models.DateTimeField()
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    # Suggested action (optional)
    suggested_verb = models.CharField(max_length=64, blank=True)
    suggested_context = models.JSONField(default=dict, blank=True)
    suggested_label = models.CharField(max_length=128, blank=True)

    # State
    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["next_due_at"]
        indexes = [
            models.Index(fields=["is_active", "next_due_at"]),
            models.Index(fields=["content_type", "owner_object_id"]),
        ]

    def __str__(self):
        return f"RecurringAction({self.title!r}, due={self.next_due_at})"
