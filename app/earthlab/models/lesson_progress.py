# earthlab/models/lesson_progress.py

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from earthlab.choices import ProgressStatus


class LessonProgress(BaseModel):
    """
    Tracks a learner's progress on a single lesson within an enrollment.

    Uses GenericForeignKey so this can reference Lesson objects
    (and potentially other lesson-like content in the future).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    enrollment = models.ForeignKey(
        "earthlab.Enrollment",
        on_delete=models.CASCADE,
        related_name="lesson_progress",
    )

    # Polymorphic lesson reference
    lesson_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    lesson_object_id = models.UUIDField()
    lesson = GenericForeignKey("lesson_content_type", "lesson_object_id")

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
                fields=["enrollment", "lesson_content_type", "lesson_object_id"],
                name="unique_lesson_progress_per_enrollment",
            ),
        ]
        indexes = [
            models.Index(fields=["enrollment", "status"]),
            models.Index(fields=["lesson_content_type", "lesson_object_id"]),
        ]

    def __str__(self):
        return f"{self.enrollment.user} — lesson {self.lesson_object_id} ({self.status})"
