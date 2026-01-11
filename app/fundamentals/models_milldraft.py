# fundamentals/models_milldraft.py
# ============================================================================
# MillDraft: Universal draft container for Phase 4 Workbench authoring
# ============================================================================

import uuid
import json
from typing import Optional, Dict, Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .bases import BaseModel


User = get_user_model()


# ============================================================================
# Enumerations
# ============================================================================

class MillDraftStatus(models.TextChoices):
    """
    MillDraft state machine.

    Transitions:
    - candidate → active (user opens draft in editor)
    - active → ready_to_promote (validation passes)
    - ready_to_promote → promoted (promotion succeeds)
    - promoted → deleted (ephemeral, after provenance preserved)
    - any → archived (user defers work)
    """
    CANDIDATE = 'candidate', 'Candidate'
    ACTIVE = 'active', 'Active'
    READY_TO_PROMOTE = 'ready_to_promote', 'Ready to Promote'
    PROMOTED = 'promoted', 'Promoted'
    ARCHIVED = 'archived', 'Archived'


class PublishSafetyClass(models.TextChoices):
    """
    PSC: Publish Safety Classification

    Determines publish behavior per content domain:
    - PSC-0 (default): Promote creates draft canonical, publish is separate
    - PSC-1 (conditional): Promote+Publish allowed if safety checks pass
    - PSC-2 (rare): Promote implies publish (admin-only, internal content)
    """
    PSC_0 = 'psc_0', 'PSC-0 (Draft Only)'
    PSC_1 = 'psc_1', 'PSC-1 (Conditional Publish)'
    PSC_2 = 'psc_2', 'PSC-2 (Auto-Publish)'


class FieldRiskClass(models.TextChoices):
    """
    FRC: Field Risk Classification

    Determines edit routing per field:
    - FRC-0 (Cosmetic): typos, formatting - editable anywhere
    - FRC-1 (Contextual): time, location, tags - creates/updates MillDraft
    - FRC-2 (Structural): content body, structure - Workbench-only
    """
    FRC_0 = 'frc_0', 'FRC-0 (Cosmetic)'
    FRC_1 = 'frc_1', 'FRC-1 (Contextual)'
    FRC_2 = 'frc_2', 'FRC-2 (Structural)'


class ValidationSeverity(models.TextChoices):
    """Validation error severity levels"""
    INFO = 'info', 'Info'
    WARNING = 'warning', 'Warning'
    ERROR = 'error', 'Error'
    CRITICAL = 'critical', 'Critical'


# ============================================================================
# MillDraft Model
# ============================================================================

class MillDraft(BaseModel):
    """
    Universal draft container for all authorial content.

    MillDraft is the core of Phase 4 Workbench authoring. All edits,
    suggestions, and authorial work flow through MillDrafts before
    promotion to canonical objects.

    Key properties:
    - Sponsor-scoped (belongs to exactly one User/Group/etc.)
    - Profile-driven (event, writing, course, etc.)
    - Dual representation (Grist + AST)
    - Provenance-tracked (source chain preserved)
    - State-machined (candidate → active → promote → archive)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ---- Sponsor Scoping ----

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name='sponsored_milldrafts'
    )
    sponsor_object_id = models.UUIDField()
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    # ---- Authorship ----

    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_milldrafts',
        help_text="Original author (may differ from submitted_by)"
    )
    author_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name for author"
    )

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_milldrafts',
        help_text="User who created this MillDraft record"
    )

    # ---- State Machine ----

    status = models.CharField(
        max_length=20,
        choices=MillDraftStatus.choices,
        default=MillDraftStatus.CANDIDATE,
        db_index=True
    )

    status_changed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Last time status changed"
    )

    # ---- Content Profile ----

    content_profile = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Content type: event, writing, course, etc."
    )

    # ---- Dual Representation (Grist + AST) ----

    grist_body = models.TextField(
        blank=True,
        default="",
        help_text="Human-editable text content (required at editing time)"
    )

    ast = models.JSONField(
        blank=True,
        null=True,
        help_text="Machine-parseable structure (required for promotion)"
    )

    ast_generation_error = models.TextField(
        blank=True,
        default="",
        help_text="Error message if AST generation failed"
    )

    # ---- Metadata ----

    title = models.CharField(max_length=255, blank=True, default="")
    summary = models.TextField(blank=True, default="")

    # ---- Provenance ----

    source_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
        db_index=True,
        help_text="Origin: stackroom, concord, gristmill, copydesk, in-editor, manual"
    )

    source_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Source-specific identifier (artifact_id, recording_id, etc.)"
    )

    provenance_bundle = models.JSONField(
        blank=True,
        default=dict,
        help_text="Complete provenance chain (source refs, content hashes, etc.)"
    )

    # ---- Canonical Object Reference ----

    canonical_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='milldraft_instances',
        help_text="Type of canonical object this draft targets"
    )
    canonical_object_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="ID of canonical object (if editing existing content)"
    )
    canonical_object = GenericForeignKey("canonical_content_type", "canonical_object_id")

    canonical_version = models.IntegerField(
        null=True,
        blank=True,
        help_text="Base version for optimistic concurrency (detect stale edits)"
    )

    # ---- Validation State ----

    validation_state = models.JSONField(
        blank=True,
        default=dict,
        help_text="Current validation errors/warnings"
    )

    validation_last_run = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time validation ran"
    )

    is_valid = models.BooleanField(
        default=False,
        help_text="True if passes hard validation (can promote)"
    )

    # ---- Publishing Metadata ----

    promoted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this draft was promoted to canonical"
    )

    promoted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promoted_milldrafts'
    )

    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this draft was archived"
    )

    archived_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='archived_milldrafts'
    )

    # ---- Soft Deletion ----

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Soft delete timestamp (recoverable)"
    )

    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_milldrafts'
    )

    class Meta:
        db_table = 'fundamentals_milldraft'
        verbose_name = 'MillDraft'
        verbose_name_plural = 'MillDrafts'
        ordering = ['-created_at']

        constraints = [
            # Sponsor scoping
            models.CheckConstraint(
                check=~models.Q(sponsor_content_type=None) & ~models.Q(sponsor_object_id=None),
                name='milldraft_sponsor_required'
            ),
        ]

        indexes = [
            # Query patterns
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id', 'status']),
            models.Index(fields=['sponsor_content_type', 'sponsor_object_id', '-created_at']),
            models.Index(fields=['content_profile', 'status']),
            models.Index(fields=['source_type', '-created_at']),
            models.Index(fields=['canonical_content_type', 'canonical_object_id']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['submitted_by', '-created_at']),
            # Review Queue queries
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['is_valid', 'status']),
        ]

    def __str__(self):
        return f"MillDraft: {self.title or 'Untitled'} ({self.get_status_display()})"

    # ---- Properties ----

    @property
    def sponsor_type(self):
        """Return the model name of the sponsor (e.g., 'user', 'group')"""
        return self.sponsor_content_type.model if self.sponsor_content_type else None

    @property
    def sponsor_id(self):
        """Return the UUID of the sponsor object"""
        return self.sponsor_object_id

    @property
    def is_candidate(self) -> bool:
        """True if in candidate state (awaiting review)"""
        return self.status == MillDraftStatus.CANDIDATE

    @property
    def is_active(self) -> bool:
        """True if actively being edited"""
        return self.status == MillDraftStatus.ACTIVE

    @property
    def is_ready_to_promote(self) -> bool:
        """True if validated and staged for promotion"""
        return self.status == MillDraftStatus.READY_TO_PROMOTE

    @property
    def is_promoted(self) -> bool:
        """True if promoted (ephemeral state)"""
        return self.status == MillDraftStatus.PROMOTED

    @property
    def is_archived(self) -> bool:
        """True if archived"""
        return self.status == MillDraftStatus.ARCHIVED

    @property
    def is_deleted(self) -> bool:
        """True if soft-deleted"""
        return self.deleted_at is not None

    @property
    def has_ast(self) -> bool:
        """True if AST has been generated"""
        return self.ast is not None and self.ast != {}

    @property
    def has_grist(self) -> bool:
        """True if Grist body exists"""
        return bool(self.grist_body and self.grist_body.strip())

    @property
    def has_canonical_target(self) -> bool:
        """True if editing existing canonical content"""
        return self.canonical_object_id is not None

    @property
    def validation_errors(self) -> list:
        """Get validation errors (severity: error or critical)"""
        return [
            err for err in self.validation_state.get('errors', [])
            if err.get('severity') in ['error', 'critical']
        ]

    @property
    def validation_warnings(self) -> list:
        """Get validation warnings"""
        return [
            err for err in self.validation_state.get('errors', [])
            if err.get('severity') == 'warning'
        ]

    # ---- State Transitions ----

    def transition_to(self, new_status: str, user: Optional[User] = None) -> bool:
        """
        Transition to a new status with validation.

        Returns True if transition successful, raises ValidationError if invalid.
        """
        # Valid transitions
        valid_transitions = {
            MillDraftStatus.CANDIDATE: [MillDraftStatus.ACTIVE, MillDraftStatus.ARCHIVED],
            MillDraftStatus.ACTIVE: [MillDraftStatus.READY_TO_PROMOTE, MillDraftStatus.ARCHIVED],
            MillDraftStatus.READY_TO_PROMOTE: [MillDraftStatus.PROMOTED, MillDraftStatus.ACTIVE, MillDraftStatus.ARCHIVED],
            MillDraftStatus.PROMOTED: [],  # Terminal state (will be deleted)
            MillDraftStatus.ARCHIVED: [MillDraftStatus.ACTIVE],  # Can reactivate from archive
        }

        current = self.status

        if new_status not in valid_transitions.get(current, []):
            raise ValidationError(
                f"Invalid transition: {current} → {new_status}"
            )

        # Perform transition
        self.status = new_status
        self.status_changed_at = timezone.now()

        # Track state-specific metadata
        if new_status == MillDraftStatus.PROMOTED:
            self.promoted_at = timezone.now()
            self.promoted_by = user
        elif new_status == MillDraftStatus.ARCHIVED:
            self.archived_at = timezone.now()
            self.archived_by = user

        self.save()
        return True

    def open_for_editing(self, user: Optional[User] = None) -> bool:
        """
        Open draft for editing (candidate → active).
        """
        if not self.is_candidate:
            raise ValidationError("Only candidate drafts can be opened for editing")

        return self.transition_to(MillDraftStatus.ACTIVE, user)

    def mark_ready_to_promote(self) -> bool:
        """
        Mark draft as ready for promotion (active → ready_to_promote).
        Requires validation to pass.
        """
        if not self.is_active:
            raise ValidationError("Only active drafts can be marked ready to promote")

        if not self.is_valid:
            raise ValidationError("Draft must pass validation before promotion")

        return self.transition_to(MillDraftStatus.READY_TO_PROMOTE)

    def promote(self, user: User) -> bool:
        """
        Promote draft to canonical (ready_to_promote → promoted).

        Note: This is an ephemeral state. After promotion succeeds and
        provenance is persisted, the MillDraft should be deleted.
        """
        if not self.is_ready_to_promote:
            raise ValidationError("Only ready drafts can be promoted")

        return self.transition_to(MillDraftStatus.PROMOTED, user)

    def archive(self, user: Optional[User] = None) -> bool:
        """
        Archive draft (any state → archived).
        """
        return self.transition_to(MillDraftStatus.ARCHIVED, user)

    def reactivate(self, user: Optional[User] = None) -> bool:
        """
        Reactivate archived draft (archived → active).
        """
        if not self.is_archived:
            raise ValidationError("Only archived drafts can be reactivated")

        self.archived_at = None
        self.archived_by = None
        return self.transition_to(MillDraftStatus.ACTIVE, user)

    # ---- Soft Deletion ----

    def soft_delete(self, user: Optional[User] = None) -> bool:
        """
        Soft delete (recoverable for 90 days).
        """
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.save()
        return True

    def restore(self) -> bool:
        """
        Restore from soft delete.
        """
        if not self.is_deleted:
            raise ValidationError("Draft is not deleted")

        self.deleted_at = None
        self.deleted_by = None
        self.save()
        return True

    # ---- Validation ----

    def run_validation(self, hard: bool = False) -> Dict[str, Any]:
        """
        Run validation checks.

        Args:
            hard: If True, enforce hard validation (required for promotion)

        Returns:
            Validation state dict with errors/warnings
        """
        errors = []

        # Schema validation (AST structure)
        if hard and not self.has_ast:
            errors.append({
                'field': 'ast',
                'severity': ValidationSeverity.ERROR,
                'message': 'AST is required for promotion'
            })

        # Field validation (required fields)
        if hard and not self.title:
            errors.append({
                'field': 'title',
                'severity': ValidationSeverity.ERROR,
                'message': 'Title is required'
            })

        # Grist validation
        if not self.has_grist:
            errors.append({
                'field': 'grist_body',
                'severity': ValidationSeverity.WARNING,
                'message': 'Grist body is empty'
            })

        # AST generation error
        if self.ast_generation_error:
            errors.append({
                'field': 'ast',
                'severity': ValidationSeverity.ERROR,
                'message': f'AST generation failed: {self.ast_generation_error}'
            })

        # Profile-specific validation would go here
        # TODO: Implement domain-specific validation (event.end > event.start, etc.)

        self.validation_state = {'errors': errors}
        self.validation_last_run = timezone.now()
        self.is_valid = not any(
            err['severity'] in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for err in errors
        )
        self.save()

        return self.validation_state

    # ---- Provenance ----

    def set_provenance(
        self,
        source_type: str,
        source_id: str,
        content_hash: Optional[str] = None,
        additional_metadata: Optional[Dict] = None
    ):
        """
        Set provenance metadata.

        Args:
            source_type: Origin (stackroom, concord, etc.)
            source_id: Source-specific identifier
            content_hash: SHA256 hash of source content
            additional_metadata: Extra provenance data
        """
        self.source_type = source_type
        self.source_id = source_id

        self.provenance_bundle = {
            'source_type': source_type,
            'source_id': source_id,
            'content_hash': content_hash,
            'created_at': timezone.now().isoformat(),
            **(additional_metadata or {})
        }

        self.save()


# ============================================================================
# Content Profile Configuration
# ============================================================================

class ContentProfileConfig(BaseModel):
    """
    Configuration for content profiles (event, writing, course, etc.).

    Defines PSC/FRC classifications and validation rules per profile.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    profile_name = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Profile identifier: event, writing, course, etc."
    )

    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")

    # PSC Classification
    publish_safety_class = models.CharField(
        max_length=10,
        choices=PublishSafetyClass.choices,
        default=PublishSafetyClass.PSC_0,
        help_text="Publish behavior for this profile"
    )

    # FRC Rules (JSON mapping field names to FRC classes)
    field_risk_rules = models.JSONField(
        blank=True,
        default=dict,
        help_text="Field → FRC mapping, e.g. {'title': 'frc_1', 'body': 'frc_2'}"
    )

    # Validation rules
    validation_schema = models.JSONField(
        blank=True,
        default=dict,
        help_text="JSON Schema for AST validation"
    )

    required_fields = models.JSONField(
        blank=True,
        default=list,
        help_text="List of required field names"
    )

    # Enabled state
    is_enabled = models.BooleanField(
        default=True,
        help_text="Feature flag: enable Workbench for this profile"
    )

    class Meta:
        db_table = 'fundamentals_content_profile_config'
        verbose_name = 'Content Profile Config'
        verbose_name_plural = 'Content Profile Configs'
        ordering = ['profile_name']

    def __str__(self):
        return f"{self.display_name} ({self.get_publish_safety_class_display()})"

    @property
    def is_psc_0(self) -> bool:
        """True if PSC-0 (draft only)"""
        return self.publish_safety_class == PublishSafetyClass.PSC_0

    @property
    def is_psc_1(self) -> bool:
        """True if PSC-1 (conditional publish)"""
        return self.publish_safety_class == PublishSafetyClass.PSC_1

    @property
    def is_psc_2(self) -> bool:
        """True if PSC-2 (auto-publish)"""
        return self.publish_safety_class == PublishSafetyClass.PSC_2

    def get_field_risk_class(self, field_name: str) -> str:
        """Get FRC for a specific field (defaults to FRC-2 if not specified)"""
        return self.field_risk_rules.get(field_name, FieldRiskClass.FRC_2)

    def validate_required_fields(self, data: Dict) -> list:
        """Check if all required fields are present"""
        errors = []
        for field in self.required_fields:
            if field not in data or not data[field]:
                errors.append({
                    'field': field,
                    'severity': ValidationSeverity.ERROR,
                    'message': f'{field} is required'
                })
        return errors
