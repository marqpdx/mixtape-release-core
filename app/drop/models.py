# drop/models.py
import uuid
from datetime import timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel


class DropWeight(models.TextChoices):
    PINNED   = "pinned",   "Pinned"
    STANDARD = "standard", "Standard"
    SOCIAL   = "social",   "Social"


_EXPIRY_DAYS = {
    DropWeight.STANDARD: 30,
    DropWeight.SOCIAL: 7,
}


class Drop(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Identity
    handle  = models.SlugField(max_length=100)
    content = models.TextField()

    # Scope — group or user via sponsor pattern
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id    = models.UUIDField()
    sponsor      = GenericForeignKey("content_type", "object_id")

    # Weight + lifecycle
    weight     = models.CharField(max_length=16, choices=DropWeight.choices, default=DropWeight.STANDARD)
    created_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drops",
    )
    expires_at  = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    # Temporal anchor
    event_date        = models.DateField(null=True, blank=True)
    related_handle    = models.CharField(max_length=200, null=True, blank=True)
    almanac_event_id  = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["content_type", "object_id", "is_archived"]),
            models.Index(fields=["weight", "is_archived"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["handle"]),
        ]

    def save(self, *args, **kwargs):
        if self.expires_at is None and self.weight in _EXPIRY_DAYS:
            self.expires_at = timezone.now() + timedelta(days=_EXPIRY_DAYS[self.weight])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Drop(@{self.handle}, {self.weight})"
