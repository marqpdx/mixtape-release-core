import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class DistillateDocumentType(models.TextChoices):
    FIELD_NOTE = "field-note", "Field Note"
    FINDING = "finding", "Finding"
    POSITION_PAPER = "position-paper", "Position Paper"
    DRAFT_ADR = "draft-adr", "Draft ADR"
    SUMMARY = "summary", "Summary"
    OTHER = "other", "Other"


class AtriumSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


class AtriumDialMode(models.TextChoices):
    EXPRESSIVE = "expressive", "Expressive"
    VERY_FOCUSED = "very_focused", "Very Focused"
    VAGUE = "vague", "Vague"


class AtriumSessionRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class AtriumSession(BaseModel):
    """
    A personal AI conversation session for a member in the Atrium surface.

    One session = one bounded conversation thread with Claude API.
    The session_context field is the member-authored memory seed — the
    CLAUDE.md equivalent that primes every new session with standing context.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    member = models.ForeignKey(
        "profiles.UserProfile",
        on_delete=models.CASCADE,
        related_name="atrium_sessions",
    )

    # Polymorphic sponsor — the Group or UserProfile that owns this Atrium surface.
    # Null = personal session (member is the implicit context).
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional member-given title; auto-populated from first query if blank.",
    )

    status = models.CharField(
        max_length=16,
        choices=AtriumSessionStatus.choices,
        default=AtriumSessionStatus.ACTIVE,
        db_index=True,
    )

    session_context = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Standing context injected at the start of every session — "
            "role, project state, working principles. The CLAUDE.md equivalent. "
            "Member-authored and editable between sessions."
        ),
    )

    dial_mode = models.CharField(
        max_length=16,
        choices=AtriumDialMode.choices,
        default=AtriumDialMode.EXPRESSIVE,
        help_text="The Dial anchor for this session — governs AI posture.",
    )

    pty_pid = models.IntegerField(
        null=True,
        blank=True,
        help_text="PID of the live PTY process for this session. Null when no PTY is running.",
    )

    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Updated on every new AtriumSessionEntry.",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Atrium Session"
        verbose_name_plural = "Atrium Sessions"

    def __str__(self):
        label = self.title or f"Session {str(self.id)[:8]}"
        return f"AtriumSession({label}) — {self.member_id}"


class AtriumSessionEntry(BaseModel):
    """
    A single exchange turn within an AtriumSession.

    Entries are append-only. role=user is the member's query;
    role=assistant is the Claude API response. Together they form the
    conversation thread stored inline for Phase 2. MillDraft promotion
    is the path for advancing a response to a canonical Puddlejump artifact.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    session = models.ForeignKey(
        AtriumSession,
        on_delete=models.CASCADE,
        related_name="entries",
    )

    role = models.CharField(
        max_length=16,
        choices=AtriumSessionRole.choices,
        db_index=True,
    )

    content = models.TextField()

    class Meta(BaseModel.Meta):
        verbose_name = "Atrium Session Entry"
        verbose_name_plural = "Atrium Session Entries"
        ordering = ["created_at"]

    def __str__(self):
        return f"AtriumSessionEntry({self.role}) in {self.session_id}"


class Distillate(models.Model):
    """
    A named knowledge artifact produced by the Distill action on an Atrium session.

    Linked to the Initiative that owns the body of work (via ApertureLog / sponsor).
    The session field records which Atrium session generated it.

    Note: `initiative` maps to the future Pulse model once that concept is fully
    designed. Migration path: Distillate.initiative → Distillate.pulse.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        "initiatives.Initiative",
        related_name="distillates",
        on_delete=models.CASCADE,
    )

    session = models.ForeignKey(
        AtriumSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="distillates",
    )

    title = models.CharField(max_length=255)
    body = models.TextField()
    document_type = models.CharField(
        max_length=32,
        choices=DistillateDocumentType.choices,
        default=DistillateDocumentType.OTHER,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Distillate"
        verbose_name_plural = "Distillates"

    def __str__(self):
        return f"Distillate({self.document_type}): {self.title[:60]}"
