import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from contexts.models import Context
from fundamentals.bases import BaseModel
from fundamentals.encrypted_fields import EncryptedTextField
from fundamentals.models import BaseData


class TrustProfile(models.TextChoices):
    STANDARD = "standard", "Standard"
    PRIVATE = "private", "Private"
    EPHEMERAL = "ephemeral", "Ephemeral"


class Conversation(BaseData):

    """
    Conversation (DM or Group), managed by contexts when lock_participants=True.
    Inherits: slug, title, summary from BaseData.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)
    trust_profile = models.CharField(
        max_length=16,
        choices=TrustProfile.choices,
        default=TrustProfile.STANDARD,
    )
    lock_participants = models.BooleanField(
        default=False,
        help_text="If true, participant list is system-managed from the bound Context anchor."
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations_created",
    )

    contexts = models.ManyToManyField(
        Context, through="ConversationContext", related_name="conversations"
    )
    class Meta:
        indexes = [models.Index(fields=["slug"])]

    def __str__(self):
        return self.title or f"Conversation {self.pk}"

    # convenience
    def default_context_link(self):
        return self.conversation_contexts.filter(is_default_for_context=True).select_related("context").first()


class ConversationParticipant(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    joined_at = models.DateTimeField(auto_now_add=True)
    # Note: last_read_at tracking moved to ConversationStatusTracker

    class Meta:
        unique_together = ("user", "conversation")

    def __str__(self):
        return f"{self.user.username} in {self.conversation}"


class ConversationContext(BaseData):
    """
    Join table between Conversation and Context, with a single MVP flag
    to mark a context's default conversation.
    """
    conversation = models.ForeignKey(
        Conversation, related_name="conversation_contexts", on_delete=models.CASCADE
    )
    context = models.ForeignKey(
        Context, related_name="conversation_contexts", on_delete=models.CASCADE
    )
    is_default_for_context = models.BooleanField(default=False)

    class Meta:
        unique_together = [("conversation", "context")]
        indexes = [
            models.Index(fields=["context", "is_default_for_context"]),
        ]

    def __str__(self):
        return f"{self.conversation} ↔ {self.context}"

    # validation: one default per context
    def clean(self):
        if self.is_default_for_context:
            exists = (
                ConversationContext.objects
                .filter(context=self.context, is_default_for_context=True)
                .exclude(pk=self.pk)
                .exists()
            )
            if exists:
                raise ValidationError(
                    {"is_default_for_context": f"Context {self.context} already has a default conversation."}
                )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ChatMessage(BaseModel):
    MESSAGE_TYPE_CHOICES = [("text", "Text"), ("voice", "Voice")]
    TRANSCRIPT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        db_index=True
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        db_index=True
    )
    text = EncryptedTextField()
    # Note: processed_text removed - not currently used

    # Voice message fields
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPE_CHOICES, default="text"
    )
    audio_file = models.ForeignKey(
        "files.StoredFile",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="chat_messages",
    )
    audio_duration_seconds = models.FloatField(null=True, blank=True)
    transcript_text = models.TextField(null=True, blank=True)
    transcript_status = models.CharField(
        max_length=20, choices=TRANSCRIPT_STATUS_CHOICES, null=True, blank=True
    )
    transcript_error = models.TextField(null=True, blank=True)
    transcript_provider = models.CharField(max_length=32, null=True, blank=True)
    transcript_model = models.CharField(max_length=64, null=True, blank=True)
    transcript_backend = models.CharField(max_length=32, null=True, blank=True)
    transcript_created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def get_reaction_summary(self):
        """Return reaction_name counts for this message"""
        from django.db.models import Count
        return self.reactions.values("reaction_name").annotate(count=Count("reaction_name")).order_by("-count")

    def __str__(self):
        return f"[{self.created_at}] {self.sender.username}: {self.text[:50]}"


class ConversationStatusTracker(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey("chat.Conversation", on_delete=models.CASCADE)
    unread_count = models.IntegerField(default=0)
    last_read_message = models.ForeignKey("chat.ChatMessage", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="+")
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "conversation")
    def __str__(self):
        return f"Status of {self.user.username} in {self.conversation.slug}"


class MessageReaction(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    reaction_name = models.CharField(max_length=50)  # 'thumbs_up', 'heart', 'laugh', etc.

    class Meta:
        unique_together = ("message", "user", "reaction_name")  # Prevents duplicate reactions
        indexes = [
            models.Index(fields=["message", "reaction_name"]),
        ]

    def __str__(self):
        return f"{self.user.username} {self.reaction_name} on {self.message.id}"


class MessageMention(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="mentions")

    # Polymorphic mentionee (User or Group)
    mentionee_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    mentionee_object_id = models.CharField(max_length=36)
    mentionee = GenericForeignKey("mentionee_content_type", "mentionee_object_id")

    # Store the original mention text for reference
    mention_text = models.CharField(max_length=100)  # "@john" or "@awesome-group"

    class Meta:
        unique_together = ("message", "mentionee_content_type", "mentionee_object_id")
        indexes = [
            models.Index(fields=["mentionee_content_type", "mentionee_object_id"]),
        ]


class UserDeviceSession(BaseModel):
    """
    Tracks active devices per user for Livewire. Phase A foundation;
    Phase B adds verification and trust state on top of this record.
    """

    class Platform(models.TextChoices):
        WEB = "web", "Web"
        DESKTOP = "desktop", "Desktop"
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_sessions",
    )
    device_id = models.UUIDField(unique=True, default=uuid.uuid4, db_index=True)
    device_name = models.CharField(max_length=128, blank=True)
    platform = models.CharField(
        max_length=16,
        choices=Platform.choices,
        default=Platform.WEB,
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    # Phase B — device identity and trust state
    verification_fingerprint = models.CharField(max_length=48, blank=True)
    is_trusted = models.BooleanField(default=False, db_index=True)
    trusted_at = models.DateTimeField(null=True, blank=True)

    # Phase C — ECDH public key (JWK format) for E2E key exchange
    public_key = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "-last_seen_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.verification_fingerprint:
            import hashlib
            raw = f"{self.user_id}:{self.device_id}"
            digest = hashlib.sha256(raw.encode()).hexdigest()[:20].upper()
            self.verification_fingerprint = " ".join(digest[i:i+5] for i in range(0, 20, 5))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} / {self.platform} / {self.device_id}"


class ConversationAuditEvent(BaseModel):
    """
    Security audit log for Conversation lifecycle events.
    Records who did what and when — never message content. ADR-0046 D9 Phase A.
    """

    class EventType(models.TextChoices):
        CONVERSATION_CREATED = "conversation_created", "Conversation Created"
        PARTICIPANT_JOINED = "participant_joined", "Participant Joined"
        PARTICIPANT_LEFT = "participant_left", "Participant Left"
        MESSAGE_SENT = "message_sent", "Message Sent"
        DEVICE_VERIFIED = "device_verified", "Device Verified"
        DEVICE_REVOKED = "device_revoked", "Device Revoked"

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="audit_events",
        db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="livewire_audit_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} / {self.conversation_id} / {self.created_at}"


class ConversationRetentionPolicy(BaseModel):
    """
    Per-Conversation retention setting. Phase A establishes the model and
    framework; Phase B wires the enforcement job to actually delete expired messages.
    A Conversation with no policy record has indefinite retention (Standard default).
    """

    class RetentionPeriod(models.TextChoices):
        ONE_DAY = "1d", "24 hours"
        SEVEN_DAYS = "7d", "7 days"
        THIRTY_DAYS = "30d", "30 days"
        NINETY_DAYS = "90d", "90 days"
        ONE_YEAR = "1y", "1 year"
        INDEFINITE = "indefinite", "Indefinite"

    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        related_name="retention_policy",
    )
    retention_period = models.CharField(
        max_length=16,
        choices=RetentionPeriod.choices,
        default=RetentionPeriod.INDEFINITE,
    )
    # Ephemeral conversations require a retention period — enforced at creation in services.
    enforcement_enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.conversation_id} / {self.retention_period}"


class ParticipantVerification(BaseModel):
    """
    Append-only log: a verifier has confirmed a participant's device identity
    within a specific Conversation. Phase B foundation for E2E trust. ADR-0046 D9 Phase B.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="verifications",
    )
    verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verifications_given",
    )
    verified_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verifications_received",
    )
    verified_device = models.ForeignKey(
        UserDeviceSession,
        on_delete=models.CASCADE,
        related_name="verifications",
    )

    class Meta:
        unique_together = [("conversation", "verifier", "verified_device")]
        indexes = [
            models.Index(fields=["conversation", "verifier"]),
            models.Index(fields=["conversation", "verified_user"]),
        ]

    def __str__(self):
        return f"{self.verifier} → {self.verified_user}/{self.verified_device_id} in {self.conversation_id}"


class ConversationKeyBundle(BaseModel):
    """
    Stores the conversation symmetric key, encrypted once per participant device.
    Only the recipient device can unwrap it using its ECDH private key.
    key_version increments on rotation (LW-C4); the latest version is authoritative.
    Phase C (ADR-0046 LW-C1/C2).
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="key_bundles",
    )
    recipient_device = models.ForeignKey(
        UserDeviceSession,
        on_delete=models.CASCADE,
        related_name="key_bundles",
    )
    encrypted_key = models.TextField()
    nonce = models.CharField(max_length=64)
    ephemeral_public_key = models.TextField()
    key_version = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = [("conversation", "recipient_device", "key_version")]
        indexes = [
            models.Index(fields=["conversation", "recipient_device"]),
        ]

    def __str__(self):
        return f"KeyBundle conv={self.conversation_id} device={self.recipient_device_id} v{self.key_version}"
