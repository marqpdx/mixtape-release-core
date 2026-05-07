import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class HubCaptureKind(models.TextChoices):
    FIX = "fix", "Let's Fix"
    NEED_MORE = "need_more", "We Need More"
    REMIND = "remind", "Remind Me"
    NOTE = "note", "Note"


class HubCaptureStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"
    PROMOTED = "promoted", "Promoted"


class HubCapture(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    kind = models.CharField(max_length=20, choices=HubCaptureKind.choices)
    body = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=HubCaptureStatus.choices,
        default=HubCaptureStatus.OPEN,
    )

    owner = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="hub_captures",
    )
    group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hub_captures",
    )

    # Elevation target — any first-class object this capture was promoted to
    promoted_to_content_type = models.ForeignKey(
        ContentType,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    promoted_to_object_id = models.UUIDField(null=True, blank=True)
    promoted_to = GenericForeignKey("promoted_to_content_type", "promoted_to_object_id")

    remind_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["owner", "status", "kind"]),
            models.Index(fields=["group", "status", "kind"]),
            models.Index(fields=["owner", "-created_at"]),
            models.Index(fields=["remind_at"]),
        ]

    def __str__(self):
        return f"[{self.kind}] {self.body[:60]}"
