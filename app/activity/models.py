# app/activity/models.py

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel
from fundamentals.models import BaseData  # you provided


# from fundamentals.bases import BaseData  # optional, see notes below


# ----------------------------------------------------------------------
# ActivityType: Canonical registry of activity codes (strongly recommended)
# ----------------------------------------------------------------------
class ActivityType(BaseData):  # instead of BaseModel
    code = models.CharField(max_length=64, unique=True)
    # title from BaseData replaces label
    # summary from BaseData can replace/augment description
    default_channel = models.CharField(
        max_length=24,
        choices=[("messages","messages"),("activity","activity"),("system","system")],
        default="activity",
    )
    default_priority = models.CharField(
        max_length=16,
        choices=[("critical","critical"),("normal","normal"),("low","low")],
        default="normal",
    )
    suppressible_by_user = models.BooleanField(default=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)


# ----------------------------------------------------------------------
# Action: Canonical "what happened" record
# ----------------------------------------------------------------------
class Action(BaseModel):
    """
    Someone (User, Group, or System) did a verb to an object (optionally in a context).
    Polymorphic actor; object + (optional) context are Generic FKs.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- ACTOR (polymorphic: User, Group, or System) ----
    actor_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="+", null=True, blank=True
    )
    actor_id = models.CharField(max_length=64, null=True, blank=True)
    actor = GenericForeignKey("actor_content_type", "actor_id")
    actor_label = models.CharField(
        max_length=64,
        default="user",
        choices=[("user", "user"), ("group", "group"), ("system", "system")],
    )

    # ---- OBJECT (what the action is about) ----
    object_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.CharField(max_length=64)
    object = GenericForeignKey("object_content_type", "object_id")

    # ---- PRIMARY CONTEXT (optional; additional contexts tracked in ActionContext) ----
    context_content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    context_id = models.CharField(max_length=64, null=True, blank=True)
    context = GenericForeignKey("context_content_type", "context_id")

    # ---- SEMANTIC ----
    # Strong typing via FK to ActivityType (registry)
    activity_type = models.ForeignKey(
        ActivityType, on_delete=models.PROTECT, related_name="actions", null=True, blank=True
    )
    # Keep verb/code strings too (useful for ad-hoc or before registry seed)
    verb = models.CharField(max_length=64)                    # e.g. "posted", "commented"
    activity_code = models.CharField(max_length=64, blank=True)  # mirror of ActivityType.code for convenience

    # Channel-of-attention hint (messages | activity | system)
    channel = models.CharField(
        max_length=24,
        default="activity",
        choices=[("messages", "messages"), ("activity", "activity"), ("system", "system")],
    )
    priority = models.CharField(
        max_length=16,
        default="normal",
        choices=[("critical", "critical"), ("normal", "normal"), ("low", "low")],
    )

    # ---- MESSAGE / THREAD METADATA (optional) ----
    # e.g. {"message_preview": "...", "thread_id": "...", "reply_to": "..."}
    metadata = models.JSONField(default=dict)

    # ---- DEDUPE / ROLLUP ----
    dedupe_key = models.CharField(max_length=128, db_index=True)
    aggregate_key = models.CharField(max_length=128, db_index=True)

    # ---- FANOUT HINTS ----
    audience = models.JSONField(default=dict)  # {"type": "...", "group_id": "...", "ids": [...], ...}

    occurs_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["dedupe_key"]),
            models.Index(fields=["aggregate_key"]),
            models.Index(fields=["occurs_at"]),
            models.Index(fields=["activity_code"]),
            models.Index(fields=["channel"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self):
        return f"{self.verb} ({self.activity_code or (self.activity_type and self.activity_type.code)})"


# ----------------------------------------------------------------------
# ActionContext: map Actions to multiple contexts (cross-post/cross-scope)
# ----------------------------------------------------------------------
class ActionContext(BaseModel):
    """
    Track all contexts where an Action appears (supports cross-posting/cross-scope).
    """
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="contexts")
    context_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    context_id = models.CharField(max_length=64)
    context = GenericForeignKey("context_content_type", "context_id")

    class Meta:
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["context_content_type", "context_id"]),
        ]

    def __str__(self):
        return f"Action {self.action_id} in {self.context_content_type}:{self.context_id}"


# ----------------------------------------------------------------------
# Notification: per-user projection (drives Activity bucket)
# ----------------------------------------------------------------------
class Notification(BaseModel):
    """
    Per-user artifact derived from an Action. Powers the dashboard Activity bucket.
    (Chat unread stays in ConversationParticipant.last_read_at; create Notifications
     only for @mentions or chat system events.)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="notifications")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")

    # ---- STATE ----
    is_read = models.BooleanField(default=False)
    is_seen = models.BooleanField(default=False)
    aggregate_count = models.PositiveIntegerField(default=1)
    last_occurred_at = models.DateTimeField()

    # toast lifecycle tracking (ephemeral → rollup)
    toast_shown_at = models.DateTimeField(null=True, blank=True)
    rolled_up_at = models.DateTimeField(null=True, blank=True)

    # ---- COPIED THROUGH (for fast queries) ----
    bucket = models.CharField(
        max_length=24,
        default="activity",
        choices=[("messages", "messages"), ("activity", "activity"), ("system", "system")],
    )
    priority = models.CharField(
        max_length=16,
        default="normal",
        choices=[("critical", "critical"), ("normal", "normal"), ("low", "low")],
    )
    dedupe_key = models.CharField(max_length=128, db_index=True)
    aggregate_key = models.CharField(max_length=128, db_index=True)

    class Meta:
        unique_together = ("recipient", "dedupe_key")
        indexes = [
            models.Index(fields=["recipient", "is_read"]),
            models.Index(fields=["recipient", "bucket", "is_read"]),
            models.Index(fields=["recipient", "aggregate_key"]),
            models.Index(fields=["recipient", "priority", "is_read"]),
            models.Index(fields=["last_occurred_at"]),
        ]

    def __str__(self):
        return f"Notif→{self.recipient_id} [{self.bucket}/{self.priority}] #{self.aggregate_count}"


# ----------------------------------------------------------------------
# NotificationPreference: user-level mute/digest/realtime per bucket or activity_code
# ----------------------------------------------------------------------
class NotificationPreference(BaseModel):
    LEVELS = [("mute", "mute"), ("digest", "digest"), ("realtime", "realtime")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")
    bucket = models.CharField(max_length=24, null=True, blank=True)        # messages | activity | system
    activity_code = models.CharField(max_length=64, null=True, blank=True) # matches ActivityType.code
    level = models.CharField(max_length=16, choices=LEVELS, default="realtime")

    class Meta:
        unique_together = ("user", "bucket", "activity_code")
        indexes = [
            models.Index(fields=["user", "bucket"]),
            models.Index(fields=["user", "activity_code"]),
        ]

    def __str__(self):
        return f"Pref {self.user_id}: {self.activity_code or self.bucket} → {self.level}"


# ----------------------------------------------------------------------
# ActionOutbox: idempotent fanout trigger for Actions
# ----------------------------------------------------------------------
class ActionOutbox(BaseModel):
    """
    Ensures an Action is dispatched to recipients via Celery (fanout task).
    """
    action = models.OneToOneField(Action, on_delete=models.CASCADE, related_name="outbox")
    dispatched_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Outbox for Action {self.action_id} (attempts={self.attempts})"


class UserNotificationSettings(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_settings")
    last_active_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    digest_frequency = models.CharField(
        max_length=16, default="daily",
        choices=[("off", "off"), ("hourly", "hourly"), ("daily", "daily"), ("weekly", "weekly")]
    )

    def __str__(self):
        return f"UserNotificationSettings({self.user_id})"


