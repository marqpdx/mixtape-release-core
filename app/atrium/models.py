import uuid

from django.db import models

from fundamentals.bases import BaseModel


class AtriumSessionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


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
