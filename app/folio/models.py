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
