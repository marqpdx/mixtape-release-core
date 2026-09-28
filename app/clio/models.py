# clio/models.py
import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.validators import RegexValidator
from django.db import models

from fundamentals.bases import BaseModel

# AD-10's own canonical example ("count-nag-keeper.junk-pile") uses a dot to
# separate a parameterizable type from its instance context, so keeper_id
# cannot use Django's stock SlugField (letters/digits/underscore/hyphen only,
# no dots). This allows dot-separated kebab/underscore segments instead.
KEEPER_ID_VALIDATOR = RegexValidator(
    regex=r"^[a-zA-Z0-9_-]+(\.[a-zA-Z0-9_-]+)*$",
    message="keeper_id must be dot-separated segments of letters, numbers, underscores, or hyphens.",
)


class ClioState(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.OneToOneField(
        "profiles.UserProfile",
        on_delete=models.CASCADE,
        related_name="clio_state",
    )
    last_surfaced_at = models.DateTimeField(null=True, blank=True)
    last_surfaced_signal = models.CharField(max_length=64, blank=True)
    # 'aperture_log' | 'neglected_content' | 'recurring_action'
    last_dismissed_at = models.DateTimeField(null=True, blank=True)
    dismiss_mode = models.CharField(
        max_length=32,
        default="session",
        choices=[
            ("session", "Session"),
            ("permanent", "Permanent"),
            ("remind_later", "Remind Later"),
        ],
    )
    remind_later_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        pass

    def __str__(self):
        return f"ClioState for profile {self.profile_id}"


# ============================================================================
# Keeper Registry (Keeper ADR AD-3, AD-10, AD-11, AD-12) — K-1
#
# Distinct from ClioState above. ClioState is the Personal Studio ambient
# nudge feature. KeeperRegistration is the campus-wide Keeper registry/relay
# layer named "Clio" in the Keeper ADR — a separate, previously-unbuilt
# surface that happens to share the app name. See clio-status.md's
# disambiguation section. K-1 scope is the model plus registration/
# deregistration endpoints only; routing (AD-11, K-2) and proactive finding
# submission (AD-12, K-3) are later phases and are not implemented here.
# ============================================================================


class KeeperFindingCadence(models.TextChoices):
    REACTIVE = "reactive", "Reactive"
    PROACTIVE = "proactive", "Proactive"
    BOTH = "both", "Both"


class KeeperClosingMode(models.TextChoices):
    DROP = "drop", "Drop"
    ARCHIVE = "archive", "Archive"


class KeeperRegistrationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class KeeperRegistration(BaseModel):
    """
    A Keeper's registration with Clio (AD-10's wire format). One row per
    registration attempt — 'active' rows are the live registry AD-3 refers
    to; 'archived' rows are retained per AD-5's archive closing mode and are
    never deleted. A dropped registration (AD-5's drop closing mode) is a
    real DELETE, not a status flag — there is no row to find afterward.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    keeper_id = models.CharField(
        max_length=200,
        db_index=True,
        validators=[KEEPER_ID_VALIDATOR],
        help_text="Kebab-case slug, e.g. 'recency-keeper' or 'count-nag-keeper.junk-pile'.",
    )
    keeper_name = models.CharField(max_length=200)
    owner_subsystem = models.CharField(
        max_length=200,
        db_index=True,
        help_text="The Django app or service that spawned and owns this Keeper.",
    )
    watch_scope = models.TextField(
        help_text="Plain-English description of what the Keeper observes. Human-readable only; not machine-parsed.",
    )
    question_shapes = models.JSONField(
        default=list,
        blank=True,
        help_text="List of {intent, description, answer_task}. Empty for proactive-only Keepers.",
    )
    intents = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True,
        help_text="Denormalized from question_shapes[].intent for indexed routing lookups (AD-11).",
    )
    finding_cadence = models.CharField(max_length=16, choices=KeeperFindingCadence.choices)
    closing_mode = models.CharField(
        max_length=16,
        choices=KeeperClosingMode.choices,
        default=KeeperClosingMode.ARCHIVE,
        help_text="Declared preference at registration time (AD-10); may be confirmed or overridden at deregistration (AD-5).",
    )
    instance_params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Keeper-specific configuration. Opaque to Clio; relayed to the Keeper unchanged.",
    )

    status = models.CharField(
        max_length=16,
        choices=KeeperRegistrationStatus.choices,
        default=KeeperRegistrationStatus.ACTIVE,
        db_index=True,
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["keeper_id"],
                condition=models.Q(status=KeeperRegistrationStatus.ACTIVE),
                name="unique_active_keeper_id",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "keeper_id"]),
        ]

    def __str__(self):
        return f"{self.keeper_id} ({self.status})"


class KeeperFindingSignal(models.TextChoices):
    NAG = "nag", "Nag"
    NOTICE = "notice", "Notice"
    SUGGEST = "suggest", "Suggest"


class KeeperFinding(BaseModel):
    """
    AD-12 proactive finding submission — store-and-defer scope (K-3 decision,
    2026-09-16, see keeper-adr-status.md). Findings are durably stored and
    queryable here, but are NOT YET wired into any surfacing mechanism.
    AD-12 says a finding should follow "Clio's existing signal-salience
    model" — that model belongs to ClioState (the Personal Studio nudge
    feature), a distinct app/feature from this campus-wide registry. Wiring
    stored findings into ClioState's salience logic is a deliberate, named
    follow-up for a later session — not done here, to avoid bundling an
    unplanned cross-surface change into this commit.

    keeper_id is a plain string, not an FK to KeeperRegistration: a finding
    must remain queryable after its Keeper is later archived or dropped.

    CLIO-1b (2026-09-28): sponsor is who this finding is *for*, per the
    platform's Sponsor-Agnostic Pattern — a UserProfile for a personal
    finding, or a Group (including the platform default group, for a
    genuinely site-wide finding) for a group-scoped one. Nullable: a
    finding submitted before this field existed, or one a Keeper never
    resolves an owner for, simply never surfaces through ClioState — a
    valid state, not an error. "Surfaced" reuses ClioState.last_surfaced_at
    as the cutoff (submitted_at > last_surfaced_at), the same convention
    Signal 1 (ApertureLog) already uses — no separate surfaced_at flag.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keeper_id = models.CharField(max_length=200, db_index=True, validators=[KEEPER_ID_VALIDATOR])
    finding_type = models.CharField(
        max_length=200,
        help_text="Keeper-defined slug describing what was found.",
    )
    finding_body = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Keeper-specific payload. Opaque beyond logging/storage, with one "
            "light convention: an optional 'message' key, a human-readable "
            "string used verbatim if this finding is surfaced through Clio."
        ),
    )
    suggested_clio_signal = models.CharField(max_length=16, choices=KeeperFindingSignal.choices)
    submitted_at = models.DateTimeField(auto_now_add=True)

    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["keeper_id", "submitted_at"]),
            models.Index(fields=["sponsor_content_type", "sponsor_object_id", "submitted_at"]),
        ]

    def __str__(self):
        return f"{self.keeper_id}: {self.finding_type}"
