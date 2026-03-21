# broadcast/models.py
"""
GroupBroadcast — steward-authored messages sent to group members.

Architecture note:
  In-app delivery flows through the existing activity fan-out (Action → ActionOutbox
  → fanout_action_task → Notification per recipient).

  Email delivery is handled by dispatch_broadcast_email_task via LanternMail/Listmonk.

  SMS is modelled here but remains disabled until Phase 2.

  BroadcastDelivery provides per-user, per-channel receipts for the steward UI.
"""
import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from fundamentals.bases import BaseModel


class GroupBroadcast(BaseModel):
    """
    A steward-authored message broadcast to some or all group members.

    Lifecycle: draft → queued → sent (or cancelled).
    If scheduled_at is null the broadcast fires immediately on queued.
    The Celery beat task picks up future-dated queued broadcasts.
    """

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        IMPORTANT = "important", "Important"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        CANCELLED = "cancelled", "Cancelled"

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-App"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"  # Phase 2 — not yet dispatched

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="broadcasts",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_broadcasts",
    )
    title = models.CharField(max_length=200)
    body = models.TextField()
    priority = models.CharField(
        max_length=16, choices=Priority.choices, default=Priority.NORMAL
    )
    # Ordered list of channels to deliver on, e.g. ["in_app", "email"]
    channels = ArrayField(
        models.CharField(max_length=16),
        default=list,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When null, fires immediately on status → queued.",
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    # Listmonk campaign ID set after email dispatch via campaign approach
    lm_campaign_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        app_label = "broadcast"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["group", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self):
        return f"GroupBroadcast({self.group_id}) — {self.title[:60]}"


class BroadcastAudience(BaseModel):
    """
    Defines who receives a broadcast.
    One record per broadcast for Phase 1 (the service handles multiple if added later).
    """

    class ScopeType(models.TextChoices):
        ALL_MEMBERS = "all_members", "All Members"
        ROLE = "role", "By Role"
        CUSTOM = "custom", "Custom User List"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    broadcast = models.ForeignKey(
        GroupBroadcast,
        on_delete=models.CASCADE,
        related_name="audiences",
    )
    scope_type = models.CharField(max_length=20, choices=ScopeType.choices)
    # For scope_type="role" — must be a valid role string (member, steward, admin, owner)
    role = models.CharField(max_length=50, blank=True, default="")
    # For scope_type="custom" — list of user UUID strings
    user_ids = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "broadcast"

    def __str__(self):
        return f"BroadcastAudience({self.scope_type}) for broadcast {self.broadcast_id}"


class BroadcastDelivery(BaseModel):
    """
    Per-user, per-channel delivery receipt. Written by the dispatch tasks.
    Gives stewards a delivery report.
    """

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-App"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class DeliveryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    broadcast = models.ForeignKey(
        GroupBroadcast,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broadcast_deliveries",
    )
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        app_label = "broadcast"
        unique_together = [("broadcast", "user", "channel")]
        indexes = [
            models.Index(fields=["broadcast", "status"]),
            models.Index(fields=["user", "channel"]),
        ]

    def __str__(self):
        return f"BroadcastDelivery({self.channel}/{self.status}) user={self.user_id}"


class UserBroadcastPreferences(BaseModel):
    """
    Per-user, per-group (or global) delivery preferences for broadcasts.

    group=null is the global default; group-specific rows take precedence.

    SMS fields are present for architectural foresight but have no effect
    until Phase 2 — the dispatch task always returns early for SMS.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="broadcast_preferences",
    )
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="member_broadcast_preferences",
        help_text="null = global default across all groups",
    )
    allow_in_app = models.BooleanField(default=True)
    allow_email = models.BooleanField(default=False)
    # Phase 2 — present in schema, not dispatched
    allow_sms = models.BooleanField(default=False)
    sms_verified = models.BooleanField(default=False)

    class Meta:
        app_label = "broadcast"
        unique_together = [("user", "group")]

    def __str__(self):
        scope = f"group={self.group_id}" if self.group_id else "global"
        return f"UserBroadcastPreferences(user={self.user_id}, {scope})"
