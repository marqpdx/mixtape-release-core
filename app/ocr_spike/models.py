from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel


class OcrSpikeArtifact(BaseModel):
    class PrivacySensitivity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        COMPLETE = "complete", "Complete"

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PREPARING = "preparing", "Preparing"
        RECOGNIZING = "recognizing", "Recognizing"
        READY_FOR_REVIEW = "ready_for_review", "Ready for review"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_filename = models.CharField(max_length=255)
    source_file_path = models.CharField(max_length=512)
    content_type = models.CharField(max_length=120, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    privacy_sensitivity = models.CharField(
        max_length=16,
        choices=PrivacySensitivity.choices,
        default=PrivacySensitivity.MEDIUM,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.UPLOADED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ocr_spike_artifacts",
    )
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "ocr_spike_artifact"
        ordering = ["-created_at"]

    def __str__(self):
        return f"OCR spike artifact {self.original_filename}"


class OcrSpikePage(BaseModel):
    class PreparationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(OcrSpikeArtifact, on_delete=models.CASCADE, related_name="pages")
    page_number = models.PositiveIntegerField()
    image_path = models.CharField(max_length=512, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    preparation_status = models.CharField(
        max_length=16,
        choices=PreparationStatus.choices,
        default=PreparationStatus.PENDING,
    )

    class Meta:
        db_table = "ocr_spike_page"
        ordering = ["page_number"]
        unique_together = [("artifact", "page_number")]

    def __str__(self):
        return f"{self.artifact_id} page {self.page_number}"


class OcrSpikeRecognitionAttempt(BaseModel):
    class Provider(models.TextChoices):
        LOCAL = "local", "Local"
        CLOUD = "cloud", "Cloud"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.ForeignKey(OcrSpikePage, on_delete=models.CASCADE, related_name="attempts")
    provider = models.CharField(max_length=16, choices=Provider.choices)
    engine_name = models.CharField(max_length=120, blank=True)
    raw_text = models.TextField(blank=True)
    raw_result_json = models.JSONField(default=dict, blank=True)
    confidence_summary = models.JSONField(default=dict, blank=True)
    processing_time_ms = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "ocr_spike_recognition_attempt"
        ordering = ["-created_at"]


class OcrSpikeEvaluation(BaseModel):
    class Outcome(models.TextChoices):
        ACCEPTED_LOCAL = "accepted_local", "Accepted local"
        CORRECTED_LOCAL = "corrected_local", "Corrected local"
        ACCEPTED_CLOUD = "accepted_cloud", "Accepted cloud"
        CORRECTED_CLOUD = "corrected_cloud", "Corrected cloud"
        UNREADABLE = "unreadable", "Unreadable"
        SKIPPED = "skipped", "Skipped"

    class CorrectionEffort(models.TextChoices):
        NONE = "none", "None"
        MINOR = "minor", "Minor"
        HEAVY = "heavy", "Heavy"
        NOT_WORTH_IT = "not_worth_it", "Not worth it"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.OneToOneField(OcrSpikePage, on_delete=models.CASCADE, related_name="evaluation")
    selected_attempt = models.ForeignKey(
        OcrSpikeRecognitionAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
    )
    final_text = models.TextField(blank=True)
    outcome = models.CharField(max_length=32, choices=Outcome.choices)
    quality_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    correction_effort = models.CharField(
        max_length=32,
        choices=CorrectionEffort.choices,
        blank=True,
    )
    search_summary = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "ocr_spike_evaluation"
        ordering = ["page__artifact_id", "page__page_number"]


class OcrSpikeFeedbackNote(models.Model):
    class Screen(models.TextChoices):
        UPLOAD = "upload", "Upload"
        PROCESSING = "processing", "Processing"
        CURATION = "curation", "Curation"
        COMPLETE = "complete", "Complete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    artifact = models.ForeignKey(
        OcrSpikeArtifact,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="feedback_notes",
    )
    page = models.ForeignKey(
        OcrSpikePage,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="feedback_notes",
    )
    screen = models.CharField(max_length=32, choices=Screen.choices)
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ocr_spike_feedback_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ocr_spike_feedback_note"
        ordering = ["-created_at"]
