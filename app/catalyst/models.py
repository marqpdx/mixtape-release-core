# catalyst/models.py
import uuid

from django.contrib.auth import get_user_model
from django.db import models


class CatalystParseJob(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PHASE1_COMPLETE = "phase1_complete"
    STATUS_ANALYZING = "analyzing"
    STATUS_COMPLETE = "complete"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PHASE1_COMPLETE, "Phase 1 Complete"),
        (STATUS_ANALYZING, "Analyzing"),
        (STATUS_COMPLETE, "Complete"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="parse_jobs",
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )

    # [{filename, size_bytes, file_type}] — stored under job_dir on disk
    uploaded_files = models.JSONField(default=list)

    # Enriched client context: general + vocabulary + post-Phase-1 additions
    client_context = models.TextField(blank=True)

    # Phase 1: {aligned: [...], unexpected: [...], absent: [...], declared_types: [...]}
    phase1_results = models.JSONField(default=dict)

    # Phase 2: {files: {filename: ai_result}, merged_registers: [...]}
    phase2_results = models.JSONField(default=dict)

    created_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
        related_name="catalyst_parse_jobs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def job_dir(self):
        from pathlib import Path
        from django.conf import settings
        return Path(settings.CATALYST_CODEX_ROOT) / "parse_jobs" / str(self.id)
