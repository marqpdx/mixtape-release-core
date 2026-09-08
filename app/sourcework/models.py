import uuid

from django.conf import settings
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


class ProvisionalThingStatus(models.TextChoices):
    PROVISIONAL = "provisional", "Provisional"
    READY = "ready", "Ready"
    EXCLUDED = "excluded", "Excluded"
    MERGED = "merged", "Merged"
    PROMOTED = "promoted", "Promoted"
    ARCHIVED = "archived", "Archived"


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
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="sourcework_connections")
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


class ProvisionalThing(BaseModel):
    """
    Mutable, non-canonical provisional object assembled from source evidence.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="provisional_things")
    possible_type = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=ProvisionalThingStatus.choices,
        default=ProvisionalThingStatus.PROVISIONAL,
        db_index=True,
    )
    preferred_name = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    organization_guess = models.CharField(max_length=255, blank=True, default="")
    relationship_context = models.TextField(blank=True, default="")
    name_source = models.CharField(max_length=32, choices=NameSource.choices, default=NameSource.UNKNOWN)
    name_confidence = models.CharField(max_length=16, choices=NameConfidence.choices, default=NameConfidence.LOW)
    name_status = models.CharField(max_length=32, choices=NameStatus.choices, default=NameStatus.NEEDS_REVIEW)
    payload = models.JSONField(default=dict, blank=True)
    evidence = models.ManyToManyField(SourceEvidence, related_name="provisional_things", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_provisional_things",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["preferred_name", "email"]
        indexes = [
            models.Index(fields=["group", "possible_type", "status"]),
            models.Index(fields=["group", "email"]),
            models.Index(fields=["name_status", "name_confidence"]),
        ]

    def __str__(self):
        return self.preferred_name or self.email or str(self.id)


class WorkingSet(BaseModel):
    """
    Durable record of assembled work. Member provisional things may have their
    own lifecycle independent of this record.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="sourcework_working_sets")
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
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["group", "status"]),
            models.Index(fields=["initiative", "status"]),
        ]

    def __str__(self):
        return self.title


class WorkingSetMembership(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    working_set = models.ForeignKey(WorkingSet, on_delete=models.CASCADE, related_name="memberships")
    provisional_thing = models.ForeignKey(ProvisionalThing, on_delete=models.CASCADE, related_name="working_set_memberships")
    status = models.CharField(max_length=24, default="active", db_index=True)
    position = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["working_set", "provisional_thing"],
                name="sourcework_unique_thing_per_working_set",
            )
        ]

    def __str__(self):
        return f"{self.working_set_id}:{self.provisional_thing_id}"
