# earthlab/models/module_progress.py

import uuid

from django.db import models

from fundamentals.bases import BaseModel
from earthlab.choices import ProgressStatus


class ModuleProgress(BaseModel):
    """
    Tracks a learner's progress on a module (Library) within an enrollment.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    enrollment = models.ForeignKey(
        "earthlab.Enrollment",
        on_delete=models.CASCADE,
        related_name="module_progress",
    )

    library = models.ForeignKey(
        "stackroom.Library",
        on_delete=models.CASCADE,
        related_name="earthlab_progress",
    )

    status = models.CharField(
        max_length=16,
        choices=ProgressStatus.choices,
        default=ProgressStatus.NOT_STARTED,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "library"],
                name="unique_module_progress_per_enrollment",
            ),
        ]
        indexes = [
            models.Index(fields=["enrollment", "status"]),
        ]

    def __str__(self):
        return f"{self.enrollment.user} — {self.library} ({self.status})"
