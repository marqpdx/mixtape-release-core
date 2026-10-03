# folio/models.py
#
# Folio First Cut — Inception + Hildegard materiality prototype
# (puddlejump/decisions/folio/folio-first-cut-build-plan.md, Phase 0).
#
# Deliberately small per the prototype spec (§4) — not the future
# FolioNode/FolioEdge graph model. Missive/material-item identity is left
# unresolved on purpose (build plan, "The open question this build is
# meant to answer, not resolve in advance").

import uuid

from django.contrib.auth import get_user_model
from django.db import models

from fundamentals.bases import BaseModel

from folio.shapes import Shape, effective_shape

User = get_user_model()


class Folio(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Blank until Gate 2 (subject extraction) or an explicit user edit sets it.
    title = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_folios",
    )

    def __str__(self):
        return self.title or f"Folio {self.id}"


class FolioInception(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    folio = models.ForeignKey(Folio, on_delete=models.CASCADE, related_name="inceptions")

    # Exact writer input. Immutable after creation — see save() below.
    raw_text = models.TextField()

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_folio_inceptions",
    )

    pipeline_version = models.CharField(max_length=50, default="v1")
    model_id = models.CharField(max_length=100, blank=True, default="")

    def save(self, *args, **kwargs):
        if self.pk:
            existing = FolioInception.objects.filter(pk=self.pk).values_list("raw_text", flat=True).first()
            if existing is not None and existing != self.raw_text:
                raise ValueError("FolioInception.raw_text is immutable after creation.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Inception for {self.folio_id} ({self.created_at})"


class CandidateType(models.TextChoices):
    SUBJECT = "subject", "Subject"
    INTENTION = "intention", "Intention"
    MATERIAL = "material", "Material"


class CandidateStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    CONFIRMED = "confirmed", "Confirmed"
    REJECTED = "rejected", "Rejected"
    AMENDED = "amended", "Amended"


class FolioMaterialCandidate(BaseModel):
    """
    One Hildegard-proposed discernment. `candidate_type` is not an
    ontology claim — it exists to support the first rendering
    (prototype spec §4).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    inception = models.ForeignKey(
        FolioInception,
        on_delete=models.CASCADE,
        related_name="material_candidates",
    )

    candidate_type = models.CharField(max_length=20, choices=CandidateType.choices)
    ordinal = models.IntegerField(null=True, blank=True)

    source_span_start = models.IntegerField()
    source_span_end = models.IntegerField()
    source_text = models.TextField()
    display_text = models.TextField(blank=True, default="")

    confidence = models.FloatField(null=True, blank=True)
    reason_code = models.CharField(max_length=100, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=CandidateStatus.choices,
        default=CandidateStatus.PROPOSED,
    )

    parent_candidate = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    def __str__(self):
        return f"{self.candidate_type}:{self.status} [{self.source_span_start}:{self.source_span_end}]"


# ---------------------------------------------------------------------------
# Folio Notes PoC (puddlejump/decisions/folio/folio-notes-poc-build-plan.md,
# folio-notes-poc-mobile-handoff.md). A different capture mode for the same
# Folio — structurally distinct from FolioInception/FolioMaterialCandidate
# and from Field Notes (build plan §3.2–3.3). Status/transcription fields
# mirror writing.Seed's voice pipeline.
# ---------------------------------------------------------------------------


class FolioNoteSource(models.TextChoices):
    VOICE = "voice", "Voice"
    TEXT = "text", "Text"


class FolioNoteStatus(models.TextChoices):
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class FolioNote(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    folio = models.ForeignKey(Folio, on_delete=models.CASCADE, related_name="notes")

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_folio_notes",
    )

    source_type = models.CharField(max_length=16, choices=FolioNoteSource.choices)

    # Exact typed input for text notes. Voice notes keep their words in
    # transcript_text instead — raw Material is canonical (build plan §4.3),
    # so neither is ever overwritten by model output.
    raw_text = models.TextField(blank=True, default="")

    # Source audio is retained (build plan §19) so transcription mistakes can
    # be inspected and a failed transcription can be retried.
    audio_file = models.ForeignKey(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="folio_notes",
    )

    transcript_text = models.TextField(blank=True, default="")
    transcript_model = models.CharField(max_length=64, blank=True, default="")
    transcript_backend = models.CharField(max_length=32, blank=True, default="")
    transcript_created_at = models.DateTimeField(null=True, blank=True)
    transcript_error = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=FolioNoteStatus.choices,
        default=FolioNoteStatus.READY,
    )

    # Plain strings validated against folio.shapes.Shape — kept separate so
    # model inference and human judgment never collapse (build plan §12).
    suggested_shape = models.CharField(max_length=32, choices=Shape.choices, blank=True, default="")
    shape_confidence = models.FloatField(null=True, blank=True)
    confirmed_shape = models.CharField(max_length=32, choices=Shape.choices, blank=True, default="")

    source = models.CharField(max_length=32, blank=True, default="")  # "mobile", "web", ...

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["folio", "created_at"]),
        ]

    @property
    def text(self) -> str:
        return self.raw_text if self.source_type == FolioNoteSource.TEXT else self.transcript_text

    @property
    def shape(self) -> str:
        return effective_shape(self.suggested_shape, self.confirmed_shape)

    def __str__(self):
        return f"FolioNote<{self.id}> {self.source_type}:{self.status}"
