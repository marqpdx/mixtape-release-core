# distribution/models.py
"""
External distribution layer for Mixtape writing.

Source         — registered external channel (LinkedIn, ActivityStream, email, etc.)
PublishEvent   — configured publish action: source channel firing + optional scheduling
ShareRecord    — immutable per-channel audit record (append-only)
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel

User = settings.AUTH_USER_MODEL


# ==============================================================================
# Source — registered distribution channel
# ==============================================================================

class SourceKind(models.TextChoices):
    ACTIVITY_STREAM = "activity_stream", "Activity Stream"
    LINKEDIN = "linkedin", "LinkedIn"
    EMAIL = "email", "Email / Newsletter"
    RSS = "rss", "RSS"
    WEBHOOK = "webhook", "Webhook"


class SourceTier(models.TextChoices):
    FREE = "free", "Free"
    COMMUNITY = "community", "Community"
    PERSONA = "persona", "Persona"


class Source(BaseModel):
    """
    Registered external distribution channel.
    Sources are platform-level or group-scoped.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    kind = models.CharField(max_length=32, choices=SourceKind.choices, db_index=True)
    label = models.CharField(max_length=128, help_text="Display name, e.g. 'Group Activity Stream'")

    # Optional: if set, channel is scoped to this group only
    group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="distribution_sources",
    )

    # JSON schema describing config fields accepted by this source's processor
    config_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON Schema for per-publish channel config fields",
    )

    tier_required = models.CharField(
        max_length=16,
        choices=SourceTier.choices,
        default=SourceTier.FREE,
        help_text="Minimum tier required to use this channel",
    )

    is_active = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        ordering = ["kind", "label"]
        verbose_name = "Distribution Source"
        verbose_name_plural = "Distribution Sources"

    def __str__(self):
        group_suffix = f" ({self.group.slug})" if self.group_id else ""
        return f"{self.label}{group_suffix}"


# ==============================================================================
# PublishEvent — configured distribution action
# ==============================================================================

class PublishEventStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    EXECUTING = "executing", "Executing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class PublishEvent(BaseModel):
    """
    A configured distribution action for a WritingPiece.

    Stores which Source channels to fire and their per-channel config.
    May be immediate (scheduled_at=None) or deferred (scheduled_at set).
    Execution creates one ShareRecord per Source channel.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    writing_piece = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="publish_events",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="publish_events_created",
    )

    # Source channel configs — list of {source_id: str, config: {...}}
    sources_config = models.JSONField(
        default=list,
        help_text="Per-channel configs: [{source_id, config}]",
    )

    # Scheduling
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="If set, defer execution until this time",
        db_index=True,
    )
    executed_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=16,
        choices=PublishEventStatus.choices,
        default=PublishEventStatus.PENDING,
        db_index=True,
    )

    # Celery task ID for cancellation of scheduled events
    celery_task_id = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "Publish Event"
        verbose_name_plural = "Publish Events"
        indexes = [
            models.Index(fields=["writing_piece", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        scheduled = f" @ {self.scheduled_at.isoformat()}" if self.scheduled_at else ""
        return f"PublishEvent<{self.status}>{scheduled} for {self.writing_piece_id}"

    @property
    def is_pending(self):
        return self.status == PublishEventStatus.PENDING

    @property
    def is_scheduled(self):
        return self.is_pending and self.scheduled_at is not None


# ==============================================================================
# ShareRecord — immutable per-channel audit record
# ==============================================================================

class ShareStatus(models.TextChoices):
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"


class ShareRecord(BaseModel):
    """
    Immutable audit record for a single Source channel emission.
    Created once per (PublishEvent, Source) pair.
    Never mutated after creation.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    publish_event = models.ForeignKey(
        PublishEvent,
        on_delete=models.CASCADE,
        related_name="share_records",
    )
    source = models.ForeignKey(
        Source,
        on_delete=models.PROTECT,
        related_name="share_records",
    )

    # Snapshot of canonical metadata at time of share
    canonical_url = models.URLField(blank=True)
    og_title = models.CharField(max_length=512, blank=True)
    synopsis = models.TextField(blank=True)
    og_image = models.URLField(blank=True)

    # Per-channel config snapshot (e.g. LinkedIn post copy)
    channel_config = models.JSONField(default=dict, blank=True)
    # Channel response (e.g. LinkedIn share URL, campaign ID)
    channel_response = models.JSONField(default=dict, blank=True)

    shared_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=16,
        choices=ShareStatus.choices,
        default=ShareStatus.SUCCESS,
        db_index=True,
    )
    failure_reason = models.CharField(max_length=512, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-shared_at"]
        verbose_name = "Share Record"
        verbose_name_plural = "Share Records"
        indexes = [
            models.Index(fields=["publish_event", "source"]),
            models.Index(fields=["source", "shared_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["publish_event", "source"],
                name="unique_share_per_event_source",
            )
        ]

    def __str__(self):
        return f"ShareRecord<{self.status}> {self.source} @ {self.shared_at.isoformat()}"
