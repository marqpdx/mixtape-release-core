import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from cloud_agents.constants import PROVIDER_ANTHROPIC_CLAUDE_CODE, PROVIDER_CHOICES
from fundamentals.bases import BaseModel


class DistillateDocumentType(models.TextChoices):
    FIELD_NOTE = "field-note", "Field Note"
    FINDING = "finding", "Finding"
    POSITION_PAPER = "position-paper", "Position Paper"
    DRAFT_ADR = "draft-adr", "Draft ADR"
    SUMMARY = "summary", "Summary"
    OTHER = "other", "Other"


class DialogueStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


class AtriumDialMode(models.TextChoices):
    EXPRESSIVE = "expressive", "Expressive"
    VERY_FOCUSED = "very_focused", "Very Focused"
    VAGUE = "vague", "Vague"


class DialogueRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"


class DialogueEntryType(models.TextChoices):
    MESSAGE = "message", "Message"
    DOCUMENT = "document", "Document"
    # A compact: the Dialogue so far, summarized; later turns start from it.
    CHECKPOINT = "checkpoint", "Checkpoint"


class DialogueEntryStatus(models.TextChoices):
    """A reply is written while it streams; a person's own entry is always done."""

    PENDING = "pending", "Pending"
    STREAMING = "streaming", "Streaming"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class Dialogue(BaseModel):
    """
    One running Dialogue in Atrium: a person and one or more AI agents (CTO, 2026-11-04).

    Its entries are the full record, and the truth: each says who spoke. The providers'
    own sessions (CloudAgentSession) are only caches that can be rebuilt from it, which
    is what lets the person switch models mid-Dialogue. A Dialogue belongs to an
    Initiative when one is set; an Initiative may hold many. Formerly AtriumSession.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    member = models.ForeignKey(
        "profiles.UserProfile",
        on_delete=models.CASCADE,
        related_name="dialogues",
    )

    # Polymorphic sponsor — the Group or UserProfile that owns this Atrium surface.
    # Null = personal Dialogue (member is the implicit context).
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
        choices=DialogueStatus.choices,
        default=DialogueStatus.ACTIVE,
        db_index=True,
    )

    session_context = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Standing context given to an agent when it joins the Dialogue — "
            "role, project state, working principles. The CLAUDE.md equivalent. "
            "Member-authored and editable."
        ),
    )

    dial_mode = models.CharField(
        max_length=16,
        choices=AtriumDialMode.choices,
        default=AtriumDialMode.EXPRESSIVE,
        help_text="The Dial anchor for this Dialogue — governs AI posture.",
    )

    ai_provider = models.CharField(
        max_length=64,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_ANTHROPIC_CLAUDE_CODE,
        help_text="The agent that answers next unless the person picks another; set to the last one used.",
    )

    initiative = models.ForeignKey(
        "initiatives.Initiative",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dialogues",
        help_text="The Initiative this Dialogue belongs to, and whose InitiativeLog it reads.",
    )

    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Updated on every new DialogueEntry.",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Dialogue"
        verbose_name_plural = "Dialogues"

    def __str__(self):
        label = self.title or f"Dialogue {str(self.id)[:8]}"
        return f"Dialogue({label}) — {self.member_id}"


class DialogueEntry(BaseModel):
    """
    One entry in a Dialogue: the person's words, or one agent's reply.

    Append-only. A reply is created pending when the person sends, filled in by the
    runtime worker as the agent writes (status streaming), and closed done or failed.
    `speaker` names which agent answered, so every agent can be told who said what.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    dialogue = models.ForeignKey(
        Dialogue,
        on_delete=models.CASCADE,
        related_name="entries",
    )

    role = models.CharField(
        max_length=16,
        choices=DialogueRole.choices,
        db_index=True,
    )

    speaker = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="For replies: the provider that answered (e.g. anthropic-claude-code, openai-codex). Blank for the person.",
    )

    content = models.TextField(blank=True, default="")

    entry_type = models.CharField(
        max_length=16,
        choices=DialogueEntryType.choices,
        default=DialogueEntryType.MESSAGE,
        db_index=True,
        help_text="message = prose bubble; document = rendered AtriumDocCard; checkpoint = a compact summary.",
    )

    document_title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Populated when entry_type=document. Extracted from the <document title> envelope.",
    )

    status = models.CharField(
        max_length=16,
        choices=DialogueEntryStatus.choices,
        default=DialogueEntryStatus.DONE,
        db_index=True,
    )

    error_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Why a reply failed: runtime_missing, runtime_not_ready, mode_not_allowed, or failed.",
    )

    action_run = models.ForeignKey(
        "initiatives.ActionRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dialogue_entries",
        help_text="The governed record of the cloud call that wrote this reply (ST-7).",
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Dialogue Entry"
        verbose_name_plural = "Dialogue Entries"
        ordering = ["created_at"]

    def __str__(self):
        return f"DialogueEntry({self.role}/{self.entry_type}) in {self.dialogue_id}"


class CloudAgentSessionStatus(models.TextChoices):
    STARTING = "starting", "Starting"
    RUNNING = "running", "Running"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class CloudAgentSession(BaseModel):
    """
    One provider's own session for a Dialogue: a cache, rebuilt from the entries.

    Holds the id the provider resumes (Claude Code's session id, Codex's thread id) and
    `seen_through`, the time of the last entry this provider has been shown, so its next
    turn starts with a catch-up of everything said since, by anyone.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dialogue = models.ForeignKey(
        Dialogue,
        on_delete=models.CASCADE,
        related_name="cloud_agent_sessions",
    )
    provider = models.CharField(max_length=64, choices=PROVIDER_CHOICES, db_index=True)
    provider_session_id = models.CharField(max_length=255, blank=True, default="")
    linux_user = models.CharField(max_length=64, blank=True, default="")
    working_directory = models.CharField(max_length=512, blank=True, default="")
    policy = models.CharField(max_length=32, default="read_only")
    status = models.CharField(
        max_length=32,
        choices=CloudAgentSessionStatus.choices,
        default=CloudAgentSessionStatus.STARTING,
        db_index=True,
    )
    seen_through = models.DateTimeField(
        null=True,
        blank=True,
        help_text="created_at of the last DialogueEntry this provider has been shown.",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Cloud Agent Session"
        verbose_name_plural = "Cloud Agent Sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["dialogue", "provider"],
                condition=models.Q(deleted_at__isnull=True),
                name="unique_active_cloud_agent_session_per_provider",
            )
        ]

    def __str__(self):
        return f"CloudAgentSession({self.provider}) for {self.dialogue_id}"


class DistillateStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"


class Distillate(models.Model):
    """
    A named knowledge artifact produced by the Distill action on a Dialogue.

    Linked to the Initiative that owns the body of work (via its InitiativeLog / sponsor).
    Written by the runtime worker on the Dialogue owner's own account: the request
    creates it pending, the run fills `body` and marks it done or failed.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        "initiatives.Initiative",
        related_name="distillates",
        on_delete=models.CASCADE,
    )

    dialogue = models.ForeignKey(
        Dialogue,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="distillates",
    )

    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    document_type = models.CharField(
        max_length=32,
        choices=DistillateDocumentType.choices,
        default=DistillateDocumentType.OTHER,
    )
    status = models.CharField(
        max_length=16,
        choices=DistillateStatus.choices,
        default=DistillateStatus.DONE,
    )
    error_code = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Distillate"
        verbose_name_plural = "Distillates"

    def __str__(self):
        return f"Distillate({self.document_type}): {self.title[:60]}"


class InitiativeDocument(models.Model):
    """
    An AI-generated document attachment in a Dialogue.

    Created when the stream parser detects a <document> envelope in a reply.
    Linked to the Initiative that owns the Dialogue so it persists and accumulates
    independent of the Dialogue itself.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        "initiatives.Initiative",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="initiative_documents",
        help_text="Initiative this document belongs to. Null for personal Dialogues with no linked Initiative.",
    )

    dialogue = models.ForeignKey(
        Dialogue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        help_text="The Dialogue that generated this document.",
    )

    dialogue_entry = models.OneToOneField(
        DialogueEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiative_document",
        help_text="The DialogueEntry (entry_type=document) this record backs.",
    )

    title = models.CharField(max_length=255)
    body = models.TextField()
    format = models.CharField(
        max_length=16,
        default="markdown",
        help_text="Body format. Default: markdown.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Initiative Document"
        verbose_name_plural = "Initiative Documents"

    def __str__(self):
        return f"InitiativeDocument: {self.title[:60]}"
