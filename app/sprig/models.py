import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class SprigKind(models.TextChoices):
    TEXT  = "text",  "Text"
    VOICE = "voice", "Voice"


class SprigStatus(models.TextChoices):
    CAPTURED  = "captured",  "Captured"   # auto-saved; precommit not yet done
    COMMITTED = "committed", "Committed"  # precommit confirmed; Relationship records created
    ARCHIVED  = "archived",  "Archived"


class Sprig(BaseModel):
    """
    Mobile relational capture affordance (Mobile Capture ADR, Affordance B).

    A Sprig is a voice or text capture that the user associates with one or
    more existing objects via a precommit step. Confirming precommit creates
    Relationship records (via RelationshipService) and transitions status to
    COMMITTED. The sponsor axis answers "whose is this" (ownership/permissions);
    Relationship records answer "what is this relevant to".
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Author — the user who captured this Sprig
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sprigs",
    )

    # Sponsor axis (Axis 1 per Relational Fabric ADR Decision 1)
    # Answers "whose is this" — one per Sprig, polymorphic (User, Group, etc.)
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    # Capture content
    kind = models.CharField(max_length=8, choices=SprigKind.choices, default=SprigKind.TEXT)
    body = models.TextField(blank=True, default="")  # typed text or final transcript

    # Voice fields — parallel to ChatMessage voice fields (Voice Capture ADR)
    audio_url = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="SeaweedFS storage key for the recorded audio clip.",
    )
    audio_duration_seconds = models.IntegerField(null=True, blank=True)
    transcript_text = models.TextField(blank=True, null=True)
    transcript_status = models.CharField(
        max_length=16,
        choices=[("pending", "Pending"), ("done", "Done"), ("failed", "Failed")],
        null=True,
        blank=True,
    )
    transcript_provider = models.CharField(max_length=32, blank=True, null=True)
    transcript_model    = models.CharField(max_length=64, blank=True, null=True)
    transcript_backend  = models.CharField(max_length=32, blank=True, null=True)
    transcript_created_at = models.DateTimeField(null=True, blank=True)
    transcript_error    = models.TextField(blank=True, null=True)

    # Lifecycle
    status = models.CharField(
        max_length=16,
        choices=SprigStatus.choices,
        default=SprigStatus.CAPTURED,
        db_index=True,
    )

    # Capture source ('ios' | 'android' | 'web')
    source = models.CharField(max_length=32, blank=True, null=True)

    metadata = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "status"]),
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "status"]),
        ]

    def __str__(self):
        return f"Sprig<{self.id}> by {self.author_id} [{self.status}]"
