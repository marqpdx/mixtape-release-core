import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.encrypted_fields import EncryptedTextField


class ExternalConnectionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"
    REVOKED = "revoked", "Revoked"
    FAILED = "failed", "Failed"


class SourceGrantStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class WorkingSetStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ARCHIVED = "archived", "Archived"


class NameSource(models.TextChoices):
    HEADER = "header", "Header"
    SIGNATURE = "signature", "Signature"
    HUMAN_VERIFIED = "human_verified", "Human verified"
    UNKNOWN = "unknown", "Unknown"


class NameConfidence(models.TextChoices):
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class NameStatus(models.TextChoices):
    READY = "ready", "Ready"
    REVIEW_SUGGESTED = "review_suggested", "Review suggested"
    NEEDS_REVIEW = "needs_review", "Needs review"


class ExternalConnection(BaseModel):
    """
    Non-secret record for an authenticated external source account.

    Credential truth must live behind credential_reference. This model records
    the provider account and operational status only.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sourcework_connections",
    )
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    provider = models.CharField(max_length=64, default="google_gmail", db_index=True)
    provider_account_id = models.CharField(max_length=255, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True, default="")
    credential_reference = models.CharField(max_length=255, blank=True, default="")
    credential_payload = EncryptedTextField(
        blank=True,
        default="",
        help_text="Encrypted provider credential payload. Never expose through agent or public API surfaces.",
    )
    provider_scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=24,
        choices=ExternalConnectionStatus.choices,
        default=ExternalConnectionStatus.DRAFT,
        db_index=True,
    )
    connected_at = models.DateTimeField(null=True, blank=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["group", "provider", "status"]),
            models.Index(fields=["owner", "provider", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "provider", "provider_account_id"],
                condition=models.Q(group__isnull=False) & ~models.Q(provider_account_id=""),
                name="unique_connected_account_per_group_provider",
            ),
            models.UniqueConstraint(
                fields=["owner", "provider", "provider_account_id"],
                condition=models.Q(group__isnull=True, owner__isnull=False) & ~models.Q(provider_account_id=""),
                name="sourcework_unique_member_provider_account",
            ),
        ]

    def __str__(self):
        return f"{self.provider}:{self.display_name or self.provider_account_id or self.id}"


class SourceGrant(BaseModel):
    """
    Bounded source permission for one initiative/work context.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connection = models.ForeignKey(ExternalConnection, on_delete=models.CASCADE, related_name="source_grants")
    initiative = models.ForeignKey(
        "initiatives.Initiative",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_grants",
    )
    resource_kind = models.CharField(max_length=64, default="gmail_label")
    resource_id = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    capabilities = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=24,
        choices=SourceGrantStatus.choices,
        default=SourceGrantStatus.ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["connection", "resource_kind", "resource_id"]),
            models.Index(fields=["initiative", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "resource_kind", "resource_id", "initiative"],
                name="sourcework_unique_grant_per_initiative",
            )
        ]

    def __str__(self):
        return f"{self.display_name} [{self.resource_kind}]"


class SourceEvidence(BaseModel):
    """
    Durable source metadata and minimal evidence for downstream provisional work.

    Full email bodies are intentionally not stored by default. Bounded excerpts
    may be stored when needed to explain a name decision.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_grant = models.ForeignKey(SourceGrant, on_delete=models.CASCADE, related_name="evidence")
    provider = models.CharField(max_length=64, default="google_gmail")
    provider_message_id = models.CharField(max_length=255)
    provider_thread_id = models.CharField(max_length=255, blank=True, default="")
    label_id = models.CharField(max_length=255, blank=True, default="")
    sender_email = models.EmailField(blank=True, default="")
    sender_display_name_raw = models.CharField(max_length=255, blank=True, default="")
    sender_header_raw = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    subject = models.TextField(blank=True, default="")
    source_fingerprint = models.CharField(max_length=128, db_index=True)
    body_snapshot_status = models.CharField(max_length=64, default="not_stored")
    bounded_excerpt = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_grant", "provider_message_id"],
                name="sourcework_unique_message_per_grant",
            )
        ]
        indexes = [
            models.Index(fields=["source_grant", "source_fingerprint"]),
            models.Index(fields=["sender_email"]),
        ]

    def __str__(self):
        return f"{self.sender_email or self.sender_header_raw} {self.sent_at or ''}".strip()


class WorkingSet(BaseModel):
    """
    Durable record of assembled work. Member provisional things may have their
    own lifecycle independent of this record.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sourcework_working_sets",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sourcework_working_sets",
    )
    initiative = models.ForeignKey(
        "initiatives.Initiative",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="working_sets",
    )
    title = models.CharField(max_length=255)
    purpose = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=WorkingSetStatus.choices,
        default=WorkingSetStatus.ACTIVE,
        db_index=True,
    )
    # Opportunity Pipeline fields — optional; populated when the set results from
    # an agent-mediated external search execution.
    source = models.CharField(
        max_length=80,
        blank=True,
        default="",
        db_index=True,
        help_text="Source identifier for this working set, e.g. 'dice', 'gmail_recruiter', 'indeed'.",
    )
    search_brief = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured search criteria that produced this working set.",
    )
    execution_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Runtime metadata for the search execution: agent, query params, counts, warnings.",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["group", "status"]),
            models.Index(fields=["owner_user", "status"]),
            models.Index(fields=["initiative", "status"]),
            models.Index(fields=["source", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(group__isnull=False) | models.Q(owner_user__isnull=False),
                name="sourcework_working_set_has_sponsor",
            ),
        ]

    def __str__(self):
        return self.title


class OpportunityProfile(BaseModel):
    """Versioned member-owned intent used to plan opportunity searches."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="opportunity_profiles",
    )
    version = models.PositiveIntegerField(default=1)
    is_current = models.BooleanField(default=True, db_index=True)
    name = models.CharField(max_length=120, default="Current opportunity profile")
    resume_label = models.CharField(max_length=255, blank=True, default="")
    resume_version = models.CharField(max_length=80, blank=True, default="")
    query_lanes = models.JSONField(default=list, blank=True)
    target_roles = models.JSONField(default=list, blank=True)
    geography = models.JSONField(default=list, blank=True)
    workplace_types = models.JSONField(default=list, blank=True)
    employment_types = models.JSONField(default=list, blank=True)
    seniority = models.JSONField(default=list, blank=True)
    strong_domains = models.JSONField(default=list, blank=True)
    strong_technologies = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)
    freshness_hours = models.PositiveIntegerField(default=72)
    preferences = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user", "version"],
                name="sourcework_unique_opportunity_profile_version",
            ),
            models.UniqueConstraint(
                fields=["owner_user"],
                condition=models.Q(is_current=True),
                name="sourcework_one_current_opportunity_profile",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_user", "is_current"]),
        ]

    def __str__(self):
        return f"{self.owner_user}: {self.name} v{self.version}"


# ---------------------------------------------------------------------------
# ProvisionalData
# ---------------------------------------------------------------------------


class ProvisionalDataState(models.TextChoices):
    """
    Lifecycle states for a ProvisionalData record.

    NEW         — just ingested; no human has touched it.
    REVIEWING   — currently open in a review surface.
    INTERESTING — flagged for closer attention; not yet acted upon.
    REJECTED    — human judged as not worth pursuing; reason stored in provenance.
    STALE       — source evidence has aged past the freshness threshold.
    ACTIONED    — an action was taken (e.g. application submitted) but the record
                  was not promoted to a durable canonical type. Distinct from
                  PROMOTED: a job might receive an application and then disappear
                  without ever deserving long-term canonical status.
    PROMOTED    — transitioned to a durable Mixtape record via promoted_content_type
                  / promoted_object_id.
    SUPERSEDED  — replaced by a newer or higher-confidence record for the same
                  underlying entity. predecessor_id may point to the replacement.
    """

    NEW = "new", "New"
    REVIEWING = "reviewing", "Reviewing"
    INTERESTING = "interesting", "Interesting"
    REJECTED = "rejected", "Rejected"
    STALE = "stale", "Stale"
    ACTIONED = "actioned", "Actioned"
    PROMOTED = "promoted", "Promoted"
    SUPERSEDED = "superseded", "Superseded"


class ProvisionalData(BaseModel):
    """
    Generic provisional record. A single model type that can carry recruiter
    contacts, job opportunities, or any future external findings. The `kind`
    field distinguishes record types; `normalized_payload` holds the typed
    normalized shape defined per kind.

    WorkingSet membership is managed through ProvisionalDataMembership (many-to-
    many) rather than a direct FK so one record can appear in multiple sets.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="provisional_data_records",
        db_index=True,
    )

    # ---- Kind and source ----
    kind = models.CharField(
        max_length=80,
        db_index=True,
        help_text="Record type: 'recruiter_contact', 'opportunity_candidate', etc.",
    )
    source_type = models.CharField(
        max_length=80,
        db_index=True,
        help_text="Origin system class: 'gmail', 'dice', 'indeed', 'manual', etc.",
    )
    source_locator = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Human-readable resource locator, e.g. a URL or label path.",
    )
    source_external_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Provider's own identifier for the source item (message ID, job ID, etc.).",
    )

    # ---- Temporal ----
    captured_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this record was ingested into Mixtape.",
    )
    observed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the source item was observed at the external source (post date, email sent date, etc.).",
    )

    # ---- Payload ----
    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Minimally-transformed source material as received. Preserve for provenance.",
    )
    normalized_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Typed normalized representation per kind (RecruiterContact shape, OpportunityCandidate shape, etc.).",
    )

    # ---- State ----
    state = models.CharField(
        max_length=24,
        choices=ProvisionalDataState.choices,
        default=ProvisionalDataState.NEW,
        db_index=True,
    )

    # ---- Evaluation ----
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Agent confidence score in [0, 1] for the normalized interpretation.",
    )
    freshness = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        help_text="Computed freshness tier: 'fresh', 'current', 'aging', 'stale_ish', 'presumed_stale'.",
    )

    # ---- Ownership ----
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provisional_data_owned",
    )

    # ---- Provenance ----
    provenance = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structured provenance record. Should capture: source, observed_at, "
            "shape_version, normalizer_version, agent, human judgment history."
        ),
    )

    # ---- Promotion target (GenericFK) ----
    promoted_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promoted_provisional_data",
        help_text="ContentType of the durable Mixtape record this was promoted to.",
    )
    promoted_object_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="PK of the durable Mixtape record this was promoted to.",
    )
    promoted_object = GenericForeignKey("promoted_content_type", "promoted_object_id")

    # ---- Source linkage ----
    source_evidence = models.ForeignKey(
        SourceEvidence,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grounded_provisional_data",
        help_text="SourceEvidence record that grounds this provisional finding.",
    )

    class Meta:
        ordering = ["-observed_at", "-created_at"]
        indexes = [
            models.Index(fields=["group", "kind", "state"]),
            models.Index(fields=["kind", "state"]),
            models.Index(fields=["owner_user", "state"]),
            models.Index(fields=["source_type", "source_external_id"]),
            models.Index(fields=["freshness", "state"]),
        ]

    def __str__(self):
        label = self.normalized_payload.get("title") or self.normalized_payload.get("preferred_name") or str(self.id)
        return f"[{self.kind}] {label} ({self.state})"


class ProvisionalDataMembership(BaseModel):
    """
    Through table linking ProvisionalData records to WorkingSets.

    Allows one ProvisionalData record to appear in multiple working sets
    (e.g. the same recruiter contact surfaced in both a Gmail import set and
    a later de-duplication set).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    working_set = models.ForeignKey(
        WorkingSet,
        on_delete=models.CASCADE,
        related_name="provisional_data_memberships",
    )
    provisional_data = models.ForeignKey(
        ProvisionalData,
        on_delete=models.CASCADE,
        related_name="working_set_memberships",
    )
    status = models.CharField(max_length=24, default="active", db_index=True)
    position = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["working_set", "provisional_data"],
                name="sourcework_unique_provisional_data_per_working_set",
            )
        ]

    def __str__(self):
        return f"{self.working_set_id}:{self.provisional_data_id}"


class OpportunityApplicationDraftStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"


class OpportunityApplicationDraft(BaseModel):
    """Member-owned, editable application material for one opportunity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="opportunity_application_drafts",
    )
    opportunity = models.ForeignKey(
        ProvisionalData,
        on_delete=models.CASCADE,
        related_name="application_drafts",
    )
    profile = models.ForeignKey(
        OpportunityProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="application_drafts",
    )
    status = models.CharField(
        max_length=24,
        choices=OpportunityApplicationDraftStatus.choices,
        default=OpportunityApplicationDraftStatus.DRAFT,
        db_index=True,
    )
    recipient_name = models.CharField(max_length=255, blank=True, default="")
    recipient_email = models.EmailField(blank=True, default="")
    letter_body = models.TextField(blank=True, default="")
    generation_context = models.JSONField(default=dict, blank=True)
    generated_by = models.CharField(max_length=40, blank=True, default="")
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner_user", "opportunity"],
                name="sourcework_one_application_draft_per_member_opportunity",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_user", "status"]),
        ]

    def __str__(self):
        title = self.opportunity.normalized_payload.get("title") or self.opportunity_id
        return f"{self.owner_user}: {title}"
