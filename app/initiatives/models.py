# initiatives/models.py

import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from fundamentals.bases import BaseModel


User = get_user_model()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class InitiativeStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SIMMERING = "simmering", "Simmering"
    PAUSED = "paused", "Paused"
    RESOLVED = "resolved", "Resolved"
    ARCHIVED = "archived", "Archived"


class SessionIntent(models.TextChoices):
    OPEN_INQUIRY = "open_inquiry", "Open Inquiry"
    FOCUSED_REVIEW = "focused_review", "Focused Review"
    DECISION_SESSION = "decision_session", "Decision Session"
    RETROSPECTIVE = "retrospective", "Retrospective"
    OTHER = "other", "Other"


class CaptureMode(models.TextChoices):
    TYPED = "typed", "Typed"
    VOICE = "voice", "Voice"
    IMPORTED = "imported", "Imported"
    PASTED = "pasted", "Pasted"


class AgentObjectOrigin(models.TextChoices):
    AGENT = "agent", "Agent"
    MANUAL = "manual", "Manual"


class DistillationState(models.TextChoices):
    PENDING = "pending", "Pending"
    PROPOSED = "proposed", "Proposed"
    CURATED = "curated", "Curated"


class ArtifactKind(models.TextChoices):
    DOCUMENT = "document", "Document"
    DECISION = "decision", "Decision"
    QUESTION = "question", "Question"
    ACTION = "action", "Action"
    ANNOTATION = "annotation", "Annotation"


class QualityScanState(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETE = "complete", "Complete"
    SKIPPED = "skipped", "Skipped"


class HandoffKind(models.TextChoices):
    BLOCKING = "blocking", "Blocking"
    FINDING = "finding", "Finding"
    QUESTION = "question", "Question"
    NOTE = "note", "Note"


class HandoffStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ActionRunStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class ActionRunExecutionMode(models.TextChoices):
    LOCAL = "local", "Local"
    LOCAL_RETRIEVAL = "local_retrieval", "Local + Retrieval"
    CLOUD = "cloud", "Cloud"


class ActionRunInitiatorType(models.TextChoices):
    HUMAN = "human", "Human"
    MODEL = "model", "Model"
    SYSTEM = "system", "System"


class TaskStatus(models.TextChoices):
    TODO = "todo", "To do"
    IN_PROGRESS = "in_progress", "In progress"
    DONE = "done", "Done"
    CANCELLED = "cancelled", "Cancelled"


class AgentCommandSource(models.TextChoices):
    MOBILE_INITIATIVES = "mobile_initiatives", "Mobile Initiatives"
    DESKTOP_INITIATIVES = "desktop_initiatives", "Desktop Initiatives"


class AgentCommandStatus(models.TextChoices):
    PARSED = "parsed", "Parsed"
    EXECUTED = "executed", "Executed"
    FAILED = "failed", "Failed"


class AgentCommandResultType(models.TextChoices):
    ACKNOWLEDGMENT = "acknowledgment", "Acknowledgment"
    GENERATED_ARTIFACT = "generated_artifact", "Generated Artifact"
    SEARCH_RESULTS = "search_results", "Search Results"


# ---------------------------------------------------------------------------
# Initiative
# ---------------------------------------------------------------------------

class Initiative(BaseModel):
    """
    A Group's living inquiry — a named direction of thinking that unfolds
    over time through AI-assisted sessions.

    v2-readiness:
    - parent: nullable self-FK for Thread support (v2)
    - rolling_summary: JSONField with four structured sections
    - sponsor: GFK to any model (Group in v0)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # --- Core fields ---
    title = models.CharField(max_length=255)
    direction = models.TextField(
        blank=True,
        default="",
        help_text="Compass heading — not a scope statement. Optional.",
    )
    status = models.CharField(
        max_length=20,
        choices=InitiativeStatus.choices,
        default=InitiativeStatus.ACTIVE,
    )
    status_note = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Optional note explaining the current status — e.g. why archived or paused. "
            "Not auto-cleared on status change; managed manually."
        ),
    )

    # --- Polymorphic sponsor (Group in v0) ---
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="sponsored_initiatives",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    # --- Thread support (v2-ready, unused in v0) ---
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="threads",
        help_text="Parent Initiative for thread structure (v2). Null = root initiative.",
    )
    thread_label = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Short label for this thread within its parent (v2).",
    )

    # --- Thread summaries (parent holds summary for each thread lane) ---
    thread_summaries = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Map of thread_id → summary object. On parent Initiatives only. "
            "Schema: {<uuid>: {label, current_direction, key_findings, open_questions, last_updated}}"
        ),
    )

    # --- Initiative Fork (seeded from another initiative) ---
    seeded_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="forks",
        help_text="Source Initiative this was forked from. Read-only after creation.",
    )
    seeded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the fork.",
    )
    seed_context = models.JSONField(
        null=True,
        blank=True,
        help_text="Snapshot of the source Initiative's rolling_summary at fork time.",
    )

    # --- Rolling summary (structured, AI-generated, human-editable) ---
    rolling_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured synthesis of all prior sessions. "
            "Schema: {current_direction, key_decisions, open_questions, where_we_are_now}"
        ),
    )
    rolling_summary_updated_at = models.DateTimeField(null=True, blank=True)
    rolling_summary_updated_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="'ai' or username — tracks who last edited the summary.",
    )

    # --- Personal Initiative flag ---
    is_personal = models.BooleanField(
        default=False,
        help_text=(
            "True for the single Personal Initiative auto-created by MemberStartupService. "
            "Prevents the fragile sponsor=user + parent=None match from becoming ambiguous "
            "once users can create their own root Initiatives."
        ),
    )

    # --- Authorship ---
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_initiatives",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "-updated_at"]),
            models.Index(fields=["status", "-updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Initiative {self.pk}"

    @property
    def rolling_summary_display(self):
        """Return rolling_summary with defaults for all four sections."""
        defaults = {
            "current_direction": "",
            "key_decisions": [],
            "open_questions": [],
            "where_we_are_now": "",
        }
        return {**defaults, **(self.rolling_summary or {})}

    def last_session_at(self):
        session = self.sessions.filter(ended_at__isnull=False).order_by("-ended_at").first()
        return session.ended_at if session else None


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class Session(BaseModel):
    """
    A discrete engagement on an Initiative — voice or text.

    raw_transcript is a JSONField (array of turn objects) for v2-readiness:
    [{"speaker": "user"|"ai", "username": str|null, "text": str, "timestamp": ISO}]
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    intent = models.CharField(
        max_length=20,
        choices=SessionIntent.choices,
        default=SessionIntent.OPEN_INQUIRY,
    )
    capture_mode = models.CharField(
        max_length=20,
        choices=CaptureMode.choices,
        default=CaptureMode.TYPED,
    )

    # --- Transcript ---
    # JSONField array of turn objects — supports single-speaker (v0) and
    # multi-speaker (v1) and imported (v2) without a migration.
    raw_transcript = models.JSONField(
        default=list,
        blank=True,
        help_text="Array of turn objects: [{speaker, username, text, timestamp}]",
    )

    # --- Distillation ---
    distillation = models.JSONField(
        default=dict,
        blank=True,
        help_text="Schema: {decisions: [], open_questions: [], actions: [], notes: ''}",
    )
    distillation_state = models.CharField(
        max_length=20,
        choices=DistillationState.choices,
        default=DistillationState.PENDING,
    )

    # --- Authorship + timing ---
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiative_sessions",
    )
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["started_at"]
        indexes = [
            models.Index(fields=["initiative", "started_at"]),
            models.Index(fields=["initiative", "distillation_state"]),
        ]

    def __str__(self):
        return f"Session [{self.intent}] on {self.initiative_id} — {self.started_at:%Y-%m-%d}"

    def close(self):
        """Mark session as ended."""
        self.ended_at = timezone.now()
        self.save(update_fields=["ended_at", "updated_at"])

    def append_turn(self, speaker, text, username=None):
        """Append a turn to raw_transcript."""
        turn = {
            "speaker": speaker,
            "username": username,
            "text": text,
            "timestamp": timezone.now().isoformat(),
        }
        transcript = list(self.raw_transcript or [])
        transcript.append(turn)
        self.raw_transcript = transcript
        self.save(update_fields=["raw_transcript", "updated_at"])
        return turn


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    """
    A structured output from a session or created directly as an annotation.

    session is nullable — Direct Annotations have no session parent.
    Direct Annotations receive an async quality scan on creation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    # Nullable — Direct Annotations have no session parent
    session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artifacts",
    )

    kind = models.CharField(
        max_length=20,
        choices=ArtifactKind.choices,
        default=ArtifactKind.DOCUMENT,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    note = models.TextField(
        blank=True,
        default="",
        help_text="Optional human note — e.g. where this came from for Direct Annotations.",
    )

    # --- Quality scan (async, non-blocking) ---
    quality_scan_result = models.JSONField(
        null=True,
        blank=True,
        help_text="Schema: {assessment: 'ok'|'advisory', note: str}",
    )
    quality_scan_state = models.CharField(
        max_length=20,
        choices=QualityScanState.choices,
        default=QualityScanState.PENDING,
    )

    # --- Puddlejump routing ---
    puddlejump_routed = models.BooleanField(
        default=False,
        help_text="Has this been submitted to Puddlejump as a candidate doc?",
    )
    puddlejump_routed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["initiative", "-created_at"]),
            models.Index(fields=["initiative", "kind"]),
            models.Index(fields=["puddlejump_routed"]),
        ]

    def __str__(self):
        return f"{self.kind}: {self.title}"

    @property
    def is_direct_annotation(self):
        return self.session_id is None

    def route_to_puddlejump(self):
        """Mark as routed. Caller is responsible for creating the candidate record."""
        self.puddlejump_routed = True
        self.puddlejump_routed_at = timezone.now()
        self.save(update_fields=["puddlejump_routed", "puddlejump_routed_at", "updated_at"])




# ---------------------------------------------------------------------------
# ActionRun
# ---------------------------------------------------------------------------

class ActionRun(BaseModel):
    """
    Durable execution record for Switchboard tool calls.

    This is the orchestration-layer audit primitive referenced by the
    Switchboard ADR. It is intentionally generic so it can record both
    human-initiated and future model-initiated tool execution chains.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_runs",
    )
    session = models.ForeignKey(
        Session,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_runs",
    )

    tool_name = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20,
        choices=ActionRunStatus.choices,
        default=ActionRunStatus.PENDING,
    )
    execution_mode = models.CharField(
        max_length=20,
        choices=ActionRunExecutionMode.choices,
        default=ActionRunExecutionMode.LOCAL,
    )
    service_name = models.CharField(max_length=80, default="switchboard")

    tenant_id = models.UUIDField()
    tenant_namespace = models.CharField(max_length=255)

    initiator_type = models.CharField(
        max_length=20,
        choices=ActionRunInitiatorType.choices,
    )
    initiator_id = models.CharField(max_length=255)
    parent_action = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_actions",
    )

    request_payload = models.JSONField(null=True, blank=True)
    result_payload = models.JSONField(null=True, blank=True)
    error_payload = models.JSONField(null=True, blank=True)
    cloud_approved = models.BooleanField(default=False)
    approval_payload = models.JSONField(null=True, blank=True)

    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["tenant_namespace", "-started_at"], name="initiatives_ar_tenant_idx"),
            models.Index(fields=["tool_name", "-started_at"], name="initiatives_ar_tool_idx"),
            models.Index(fields=["status", "-started_at"], name="initiatives_ar_status_idx"),
            models.Index(fields=["initiator_type", "initiator_id"], name="initiatives_ar_init_idx"),
        ]

    def __str__(self):
        return f"ActionRun [{self.tool_name}] {self.status}"


# ---------------------------------------------------------------------------
# AgentToken — v2-ready stub
# ---------------------------------------------------------------------------

class AgentToken(BaseModel):
    """
    Short-lived, Initiative-scoped token for agent (Claude Code) access.

    Not exposed via API in v0. Designed alongside Initiative so the v2
    Agent-Facing API doesn't require a new auth subsystem.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.CASCADE,
        related_name="agent_tokens",
    )
    token = models.CharField(max_length=64, unique=True)
    issued_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="issued_agent_tokens",
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"AgentToken for {self.initiative_id} (expires {self.expires_at:%Y-%m-%d})"

    @property
    def is_valid(self):
        return self.revoked_at is None and self.expires_at > timezone.now()


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

class Handoff(BaseModel):
    """
    A cross-thread message — blocking condition, finding, question, or note.

    Always belongs to the root parent Initiative. from_thread / to_thread
    identify the source and target workstream lanes. to_thread=null means
    broadcast to all threads.

    Only 'blocking' kind has meaningful status (open → resolved/withdrawn).
    All other kinds are informational and require no resolution.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.CASCADE,
        related_name="handoffs",
        help_text="Always the root parent Initiative.",
    )
    kind = models.CharField(
        max_length=20,
        choices=HandoffKind.choices,
        default=HandoffKind.BLOCKING,
    )
    content = models.TextField(
        help_text="The message — blocking condition, finding, question, or note.",
    )

    # --- Thread routing ---
    from_thread = models.ForeignKey(
        Initiative,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="outgoing_handoffs",
        help_text="Thread that created this handoff. Null = from root session or human.",
    )
    to_thread = models.ForeignKey(
        Initiative,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incoming_handoffs",
        help_text="Directed at a specific thread. Null = broadcast to all threads.",
    )

    # --- Resolution (meaningful for blocking kind only) ---
    status = models.CharField(
        max_length=20,
        choices=HandoffStatus.choices,
        default=HandoffStatus.OPEN,
    )
    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Username or 'ai'.",
    )

    # --- Authorship ---
    authored_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Username or 'ai' — tracks whether human or AI wrote it.",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_handoffs",
        help_text="Null if AI-authored.",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["initiative", "status"], name="initiatives_initiat_fcf744_idx"),
            models.Index(fields=["initiative", "kind"], name="initiatives_initiat_363458_idx"),
            models.Index(fields=["to_thread", "status"], name="initiatives_to_thre_5ac371_idx"),
        ]

    def __str__(self):
        return f"Handoff [{self.kind}] on {self.initiative_id}: {self.content[:60]}"

    def resolve(self, resolution, resolved_by):
        """Resolve a blocking handoff."""
        self.status = HandoffStatus.RESOLVED
        self.resolution = resolution
        self.resolved_by = resolved_by
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolution", "resolved_by", "resolved_at", "updated_at"])


# ---------------------------------------------------------------------------
# ApertureLog + ApertureLogEntry
# ---------------------------------------------------------------------------

class ApertureLogEntryKind(models.TextChoices):
    PROSE = "prose", "Prose"
    LEDGER = "ledger", "Ledger"
    HANDOFF = "handoff", "Handoff"
    EMPH = "emph", "Emphasis"
    SEED_SPAWN = "seed_spawn", "Seed Spawn"
    RUN_BOUNDARY = "run_boundary", "Run Boundary"


class LedgerEventType(models.TextChoices):
    SESSION_STARTED = "session_started", "Session started"
    SESSION_ENDED = "session_ended", "Session ended"
    DOCUMENT_BOUND = "document_bound", "Document bound"
    SEED_PROMOTED = "seed_promoted", "Seed promoted"
    STATUS_CHANGED = "status_changed", "Status changed"
    ARTIFACT_LINKED = "artifact_linked", "Artifact linked"
    MATERIAL_LATE_BOUND = "material_late_bound", "Material late-bound"


class ApertureLog(BaseModel):
    """
    The authoritative narrative spine of an Initiative.
    One per Initiative, created automatically alongside it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.OneToOneField(
        Initiative,
        on_delete=models.CASCADE,
        related_name="aperture_log",
    )
    last_handoff_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Denormalized — updated on every ApertureLogEntry with kind='handoff'.",
    )

    class Meta(BaseModel.Meta):
        pass

    def __str__(self):
        return f"ApertureLog for {self.initiative_id}"


class ApertureLogEntry(BaseModel):
    """
    Individual entries in an ApertureLog stream. Either human-authored or system-generated.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    aperture_log = models.ForeignKey(
        ApertureLog,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    kind = models.CharField(
        max_length=20,
        choices=ApertureLogEntryKind.choices,
        default=ApertureLogEntryKind.PROSE,
    )
    body = models.TextField(
        blank=True,
        default="",
        help_text="Human-authored content for prose/handoff entries; system description for ledger entries.",
    )
    emph_note = models.TextField(
        blank=True,
        default="",
        help_text="The quoted note from /emph. Blank for all non-emph kinds.",
    )
    ledger_event_type = models.CharField(
        max_length=40,
        choices=LedgerEventType.choices,
        blank=True,
        default="",
    )
    ledger_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Structured event payload for ledger entries. Schema varies by ledger_event_type.",
    )

    # GFK for seed_spawn entries
    spawned_seed_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    spawned_seed_object_id = models.UUIDField(null=True, blank=True)
    spawned_seed = GenericForeignKey("spawned_seed_content_type", "spawned_seed_object_id")

    emph_is_summary_candidate = models.BooleanField(
        default=False,
        help_text="System has proposed this /emph as a rolling summary candidate.",
    )
    emph_accepted_to_summary = models.BooleanField(
        default=False,
        help_text="Member accepted this /emph into the rolling summary.",
    )
    is_system_generated = models.BooleanField(
        default=False,
        help_text="True for ledger entries and system-appended /emph candidates. Not editable by member.",
    )
    authored_by = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="username for member entries; 'system' for ledger entries.",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="aperture_log_entries",
        help_text="Null for system-generated entries.",
    )
    archived_at = models.DateTimeField(null=True, blank=True, default=None)

    class Meta(BaseModel.Meta):
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["aperture_log", "created_at"]),
            models.Index(fields=["aperture_log", "kind"]),
            models.Index(fields=["aperture_log", "kind", "emph_is_summary_candidate"]),
        ]

    def __str__(self):
        return f"ApertureLogEntry [{self.kind}] on {self.aperture_log_id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep ApertureLog.last_handoff_at in sync
        if self.kind == ApertureLogEntryKind.HANDOFF:
            ApertureLog.objects.filter(pk=self.aperture_log_id).update(
                last_handoff_at=self.created_at
            )


# ---------------------------------------------------------------------------
# Reminder
# ---------------------------------------------------------------------------

class ReminderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    SNOOZED = "snoozed", "Snoozed"


class AgentCommand(BaseModel):
    """
    Persisted parse/confirm record for agent command UX across mobile and desktop.

    This gives the client a stable resource for parse, confirm, and result
    display without exposing the verb-specific execution seams directly.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="initiative_agent_commands",
        null=True,
        blank=True,
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_commands",
    )
    source = models.CharField(
        max_length=40,
        choices=AgentCommandSource.choices,
        default=AgentCommandSource.MOBILE_INITIATIVES,
    )
    capture_mode = models.CharField(
        max_length=20,
        choices=CaptureMode.choices,
        default=CaptureMode.TYPED,
    )
    draft_session_id = models.CharField(max_length=255, blank=True, default="")
    raw_input = models.TextField()

    parsed_verb = models.CharField(max_length=40, blank=True, default="")
    confidence = models.FloatField(null=True, blank=True)
    parsed_title = models.CharField(max_length=255, blank=True, default="")
    parsed_summary = models.TextField(blank=True, default="")
    parsed_fields = models.JSONField(default=dict, blank=True)
    parse_metadata = models.JSONField(default=dict, blank=True)
    generated_text = models.TextField(blank=True, default="")
    needs_clarification = models.BooleanField(default=False)
    clarification_reason = models.TextField(blank=True, default="")

    edited_fields = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=AgentCommandStatus.choices,
        default=AgentCommandStatus.PARSED,
    )
    executed_verb = models.CharField(max_length=40, blank=True, default="")
    result_type = models.CharField(
        max_length=30,
        choices=AgentCommandResultType.choices,
        blank=True,
        default="",
    )
    result_payload = models.JSONField(default=dict, blank=True)
    error_payload = models.JSONField(default=dict, blank=True)
    follow_up_suggestions = models.JSONField(default=list, blank=True)
    routing_metadata = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiative_agent_commands",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "-created_at"], name="init_agcmd_source_idx"),
            models.Index(fields=["initiative", "-created_at"], name="initiatives_agentcmd_init_idx"),
            models.Index(fields=["status", "-created_at"], name="init_agcmd_status_idx"),
            models.Index(fields=["created_by", "-created_at"], name="initiatives_agentcmd_user_idx"),
        ]

    def __str__(self):
        return self.parsed_title or self.raw_input[:60] or f"AgentCommand {self.pk}"


class Note(BaseModel):
    """
    Canonical agent-capture object for ad hoc notes and observations.

    This remains distinct from writing.Seed. Mobile and desktop agent verbs
    should persist quick capture here first, then route or promote elsewhere
    if richer workflows need it later.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="initiative_notes",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    capture_mode = models.CharField(
        max_length=20,
        choices=CaptureMode.choices,
        default=CaptureMode.TYPED,
    )
    origin = models.CharField(
        max_length=20,
        choices=AgentObjectOrigin.choices,
        default=AgentObjectOrigin.AGENT,
    )
    raw_input = models.TextField(blank=True, default="")
    parsed_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="initiative_notes",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "-created_at"], name="initiatives_note_sponsor_idx"),
            models.Index(fields=["initiative", "-created_at"], name="initiatives_note_init_idx"),
        ]

    def __str__(self):
        return self.title or f"Note {self.pk}"


class Reminder(BaseModel):
    """
    A time-based reminder attached to an Initiative.
    Model and migration only in v0 — no API endpoint until v1.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="initiative_reminders",
        null=True,
        blank=True,
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")
    title = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField()
    remind_at = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=ReminderStatus.choices,
        default=ReminderStatus.PENDING,
    )
    snoozed_until = models.DateTimeField(null=True, blank=True)
    capture_mode = models.CharField(
        max_length=20,
        choices=CaptureMode.choices,
        default=CaptureMode.TYPED,
    )
    origin = models.CharField(
        max_length=20,
        choices=AgentObjectOrigin.choices,
        default=AgentObjectOrigin.AGENT,
    )
    raw_input = models.TextField(blank=True, default="")
    parsed_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
    )

    class Meta(BaseModel.Meta):
        ordering = ["remind_at"]
        indexes = [
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "remind_at"], name="initiatives_rem_sponsor_idx"),
            models.Index(fields=["initiative", "remind_at"], name="initiatives_rem_init_idx"),
            models.Index(fields=["status", "remind_at"], name="initiatives_rem_status_idx"),
        ]

    def __str__(self):
        return f"Reminder [{self.status}] at {self.remind_at} for initiative {self.initiative_id}"


class Task(BaseModel):
    """
    Canonical agent task object for mobile and desktop command surfaces.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="initiative_tasks",
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    initiative = models.ForeignKey(
        Initiative,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    title = models.CharField(max_length=255)
    details = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.TODO,
    )
    due_at = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_initiative_tasks",
    )
    capture_mode = models.CharField(
        max_length=20,
        choices=CaptureMode.choices,
        default=CaptureMode.TYPED,
    )
    origin = models.CharField(
        max_length=20,
        choices=AgentObjectOrigin.choices,
        default=AgentObjectOrigin.AGENT,
    )
    raw_input = models.TextField(blank=True, default="")
    parsed_metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_initiative_tasks",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "-created_at"], name="initiatives_task_sponsor_idx"),
            models.Index(fields=["initiative", "-created_at"], name="initiatives_task_init_idx"),
            models.Index(fields=["status", "due_at"], name="initiatives_task_status_idx"),
        ]

    def __str__(self):
        return self.title


# ============================================================================
# Initiatives Voice Transcription Job (IM-7c)
# ============================================================================

class AgentTranscriptionStatus(models.TextChoices):
    PROCESSING = "processing", "Processing"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


class AgentTranscriptionJob(BaseModel):
    """
    Ephemeral record tracking a mobile voice command transcription job.
    Audio is stored temporarily and deleted once transcription completes.
    """

    status = models.CharField(
        max_length=20,
        choices=AgentTranscriptionStatus.choices,
        default=AgentTranscriptionStatus.PROCESSING,
    )
    audio_path = models.CharField(max_length=512, blank=True)
    transcription_text = models.TextField(blank=True)
    failure_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_transcription_jobs",
    )

    class Meta(BaseModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="init_transcription_status_idx"),
        ]

    def __str__(self):
        return f"TranscriptionJob({self.status}) {self.id}"
