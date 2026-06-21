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
