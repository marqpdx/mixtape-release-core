"""
Ariadne — core schema (build spec §3, Phases P4 and minimal P5).

P4 (Source and processing, Conceptual records) and P5-minimal (Lens +
Discovery Run mechanics only, enough to run and review one real
Discovery Run) live here. Likeness/anchor/accession/branch/honing-ratio/
shadow-log (the addendum vocabulary, ariadne-addendum-likeness.md §11)
is still deliberately NOT modeled -- the CTO's 2026-10-12 decision was to
build only the minimum P5 needs, and to let Likeness/branch/accession
schema co-emerge after seeing a real Run's output rather than be
designed now. CandidateSuppression (time-limited Drop without erasure)
is also skipped for the same reason -- RunCandidate.disposition="drop"
is enough for a first Run's review step.

The tending-spike §4 fork (where shadow proposals live) is resolved:
Stackroom's `Proposal` model (mixtape-release-stackroom/app/stackroom/
models/proposal.py), not an Ariadne-local table -- decided 2026-10-12 to
avoid building a second proposal-review system. Not wired up here: no
Tending logic exists yet to produce a shadow proposal, so extending
Stackroom's model with run_id/action_kind/etc. now would add unused
columns ahead of a real caller. That extension happens when Tending's
shadow-log producer is actually built.

Tables live in the dedicated `ariadne` Postgres schema reserved by P2
(`ariadne_create_schema` management command), not the public schema most
other apps use -- decided 2026-10-12, CTO's call, since that schema's
whole stated purpose was holding future Ariadne tables. Achieved via
Django's db_table schema-qualification trick: a db_table value that
already contains embedded double quotes is passed through by
connection.ops.quote_name() unmodified, so `'ariadne"."source_document'`
becomes the identifier `"ariadne"."source_document"` in generated SQL.
There's no other precedent for this in the codebase (ocr_spike and every
other app use flat db_table names in public) -- this is the first.

ADR classification, stakes derivation, and the new 2026-10-12 vocabulary
(work_state, class: reference, _deprecated/ -> status: deprecated) are
not modeled here. They inform Concept/ConceptAssertion curation logic in
P5+, not this table group.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel

SCHEMA = "ariadne"


def _table(name: str) -> str:
    return f'{SCHEMA}"."{name}'


# ---------------------------------------------------------------------------
# Source and processing
# ---------------------------------------------------------------------------

class SourceDocument(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_system = models.CharField(max_length=64, help_text="e.g. 'puddlejump'")
    source_key = models.CharField(max_length=512, help_text="Stable key within source_system, e.g. a rel_path")
    title = models.CharField(max_length=512, blank=True)
    document_type = models.CharField(max_length=64, blank=True, help_text="e.g. 'adr', 'spike', 'field-note'")
    uri = models.CharField(max_length=1024, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    visibility = models.CharField(max_length=32, default="internal")
    current_revision = models.ForeignKey(
        "SourceRevision", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="current_for_document",
    )

    class Meta:
        db_table = _table("source_document")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["source_system", "source_key"], name="ariadne_sourcedoc_unique_key"),
        ]

    def __str__(self):
        return f"{self.source_system}:{self.source_key}"


class SourceRevision(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name="revisions")
    content_hash = models.CharField(max_length=128)
    normalized_hash = models.CharField(max_length=128, blank=True)
    metadata_hash = models.CharField(max_length=128, blank=True)
    captured_at = models.DateTimeField()
    parser_version = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default="captured")

    class Meta:
        db_table = _table("source_revision")
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.document_id} @ {self.content_hash[:12]}"


class SourceSection(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(SourceRevision, on_delete=models.CASCADE, related_name="sections")
    heading_path = models.CharField(max_length=1024, blank=True, help_text="e.g. '3 > Conceptual records'")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    content_hash = models.CharField(max_length=128)
    source_offsets = models.JSONField(default=dict, blank=True, help_text="{'start': int, 'end': int}")

    class Meta:
        db_table = _table("source_section")
        ordering = ["revision", "ordinal"]


class Passage(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(SourceRevision, on_delete=models.CASCADE, related_name="passages")
    section = models.ForeignKey(SourceSection, on_delete=models.SET_NULL, null=True, blank=True, related_name="passages")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    content_hash = models.CharField(max_length=128)
    context_hash = models.CharField(max_length=128, blank=True)
    start_offset = models.PositiveIntegerField(null=True, blank=True)
    end_offset = models.PositiveIntegerField(null=True, blank=True)
    embedding_status = models.CharField(max_length=32, default="none")

    class Meta:
        db_table = _table("passage")
        ordering = ["revision", "ordinal"]


class ProcessingStageResult(BaseModel):
    """Generic record of one processing stage's run over some target
    (a SourceRevision, a Passage, a Concept, ...) -- the build spec
    doesn't name what a stage targets, so this follows the codebase's
    sponsor-agnostic GFK convention rather than a direct FK to one model."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stage_name = models.CharField(max_length=128)
    target_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    target_object_id = models.UUIDField(null=True, blank=True)
    target = GenericForeignKey("target_content_type", "target_object_id")
    input_fingerprint = models.CharField(max_length=128, blank=True)
    processor_version = models.CharField(max_length=64, blank=True)
    model_version = models.CharField(max_length=64, blank=True)
    config_hash = models.CharField(max_length=128, blank=True)
    output_ref = models.CharField(max_length=512, blank=True)
    status = models.CharField(max_length=32, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = _table("processing_stage_result")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_content_type", "target_object_id"])]


class DerivedDependency(BaseModel):
    """Links a derived output (any model instance -- a ConceptMention,
    ConceptAssertion, etc.) to the exact source revision/passage/config/
    model version it depended on, per build spec §3."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    derived_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    derived_object_id = models.UUIDField()
    derived_output = GenericForeignKey("derived_content_type", "derived_object_id")
    source_revision = models.ForeignKey(SourceRevision, on_delete=models.SET_NULL, null=True, blank=True, related_name="derived_dependencies")
    passage = models.ForeignKey(Passage, on_delete=models.SET_NULL, null=True, blank=True, related_name="derived_dependencies")
    config_hash = models.CharField(max_length=128, blank=True)
    model_version = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = _table("derived_dependency")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["derived_content_type", "derived_object_id"])]


# ---------------------------------------------------------------------------
# Conceptual records
# ---------------------------------------------------------------------------

class Concept(BaseModel):
    class Status(models.TextChoices):
        CANDIDATE = "candidate", "Candidate"
        CURATED = "curated", "Curated"
        CANONICAL = "canonical", "Canonical"
        RETIRED = "retired", "Retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    preferred_label = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CANDIDATE)

    class Meta:
        db_table = _table("concept")
        ordering = ["preferred_label"]

    def __str__(self):
        return self.preferred_label


class ConceptAlias(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=256)
    alias_type = models.CharField(max_length=32, default="synonym")
    language = models.CharField(max_length=16, default="en")

    class Meta:
        db_table = _table("concept_alias")
        ordering = ["concept", "alias"]
        constraints = [
            models.UniqueConstraint(fields=["concept", "alias", "language"], name="ariadne_alias_unique_per_concept"),
        ]


class ConceptMention(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="mentions")
    passage = models.ForeignKey(Passage, on_delete=models.CASCADE, related_name="concept_mentions")
    start_offset = models.PositiveIntegerField()
    end_offset = models.PositiveIntegerField()
    match_method = models.CharField(max_length=32, help_text="e.g. 'exact', 'alias', 'ner'")
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = _table("concept_mention")
        ordering = ["-created_at"]


class ConceptAssertion(BaseModel):
    """A claim with provenance, not an accepted fact by default -- see
    build spec §3's explicit warning against treating semantic-neighbor
    edges as accepted relationships."""

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACCEPTED = "accepted", "Accepted"
        DISPUTED = "disputed", "Disputed"
        REJECTED = "rejected", "Rejected"
        SUPERSEDED = "superseded", "Superseded"
        STALE = "stale", "Stale"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="subject_assertions")
    predicate = models.CharField(max_length=128)
    object_concept = models.ForeignKey(Concept, on_delete=models.SET_NULL, null=True, blank=True, related_name="object_assertions")
    claim_text = models.TextField(blank=True, help_text="Free-text claim when object_concept is null")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    extraction_method = models.CharField(max_length=64, blank=True)
    extractor_version = models.CharField(max_length=64, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = _table("concept_assertion")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject_concept_id} {self.predicate} ({self.status})"


class AssertionEvidence(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assertion = models.ForeignKey(ConceptAssertion, on_delete=models.CASCADE, related_name="evidence")
    passage = models.ForeignKey(Passage, on_delete=models.CASCADE, related_name="assertion_evidence")
    quote_offsets = models.JSONField(default=dict, blank=True, help_text="{'start': int, 'end': int}")
    evidence_role = models.CharField(
        max_length=16,
        choices=[("supports", "Supports"), ("contradicts", "Contradicts"), ("context", "Context")],
        default="supports",
    )
    strength = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = _table("assertion_evidence")
        ordering = ["-created_at"]


class ConceptArtifactLink(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="artifact_links")
    document = models.ForeignKey(SourceDocument, on_delete=models.CASCADE, related_name="concept_links")
    link_type = models.CharField(max_length=32, help_text="e.g. 'defines', 'discusses', 'references'")
    evidence = models.ForeignKey(AssertionEvidence, on_delete=models.SET_NULL, null=True, blank=True, related_name="artifact_links")

    class Meta:
        db_table = _table("concept_artifact_link")
        ordering = ["-created_at"]


# ---------------------------------------------------------------------------
# Discovery and curation (P5, minimal) -- enough to run and review one real
# Discovery Run. No Likeness/branch/accession/anchor/honing-ratio/shadow-log
# here; see module docstring.
# ---------------------------------------------------------------------------

class Lens(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    active_version = models.ForeignKey(
        "LensVersion", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="active_for_lens",
    )

    class Meta:
        db_table = _table("lens")
        ordering = ["name"]

    def __str__(self):
        return self.name


class LensVersion(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lens = models.ForeignKey(Lens, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    config = models.JSONField(default=dict, blank=True, help_text="Source weights, time window, filters, ranking -- immutable once created")
    config_hash = models.CharField(max_length=128)

    class Meta:
        db_table = _table("lens_version")
        ordering = ["lens", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["lens", "version"], name="ariadne_lensversion_unique_version"),
        ]


class CorpusSnapshot(BaseModel):
    """Immutable manifest of source revisions eligible for a Run, so an
    identical Lens + snapshot rerun can be linked to the earlier result
    rather than counted as an independent discovery (build spec §3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manifest_hash = models.CharField(max_length=128)
    source_revision_ids = models.JSONField(default=list, help_text="List of SourceRevision UUIDs eligible for this snapshot")
    captured_at = models.DateTimeField()

    class Meta:
        db_table = _table("corpus_snapshot")
        ordering = ["-captured_at"]


class DiscoveryRun(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lens_version = models.ForeignKey(LensVersion, on_delete=models.PROTECT, related_name="discovery_runs")
    corpus_snapshot = models.ForeignKey(CorpusSnapshot, on_delete=models.PROTECT, related_name="discovery_runs")
    extractor_versions = models.JSONField(default=dict, blank=True)
    model_versions = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    target_concept_count = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = _table("discovery_run")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run {self.id} ({self.status})"


class RunCandidate(BaseModel):
    class Disposition(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPT = "accept", "Accept"
        DECLINE = "decline", "Decline"
        DEFER = "defer", "Defer"
        DROP = "drop", "Drop"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(DiscoveryRun, on_delete=models.CASCADE, related_name="candidates")
    concept_or_phrase_key = models.CharField(max_length=256)
    rank = models.PositiveIntegerField()
    score = models.FloatField()
    score_components = models.JSONField(default=dict, blank=True)
    summary = models.TextField(blank=True)
    appearance_key = models.CharField(max_length=256, blank=True, help_text="Dedup key stable across reruns of the same branch")
    disposition = models.CharField(max_length=16, choices=Disposition.choices, default=Disposition.PENDING)
    disposition_reason = models.TextField(blank=True)
    disposition_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = _table("run_candidate")
        ordering = ["run", "rank"]


class EvidencePacket(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(DiscoveryRun, on_delete=models.CASCADE, related_name="evidence_packets")
    candidate_key = models.CharField(max_length=256)
    retrieval_config_hash = models.CharField(max_length=128, blank=True)
    source_revision_ids = models.JSONField(default=list, blank=True)
    passage_ids = models.JSONField(default=list, blank=True)
    packet_version = models.PositiveIntegerField(default=1)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=32, default="draft")

    class Meta:
        db_table = _table("evidence_packet")
        ordering = ["run", "candidate_key", "-packet_version"]


class CurationDecision(BaseModel):
    """Append-only by convention (no update path is provided anywhere in
    this codebase for this model) -- a later decision supersedes an
    earlier one via `supersedes`, never by editing it in place."""

    class Action(models.TextChoices):
        ACCEPT = "accept", "Accept"
        DECLINE = "decline", "Decline"
        DEFER = "defer", "Defer"
        DROP = "drop", "Drop"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(DiscoveryRun, on_delete=models.CASCADE, related_name="curation_decisions")
    candidate_key = models.CharField(max_length=256)
    action = models.CharField(max_length=16, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    actor_label = models.CharField(max_length=128, blank=True, help_text="Set when the actor is an agent, not a Django user")
    reason = models.TextField(blank=True)
    supersedes = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="superseded_by")

    class Meta:
        db_table = _table("curation_decision")
        ordering = ["-created_at"]
