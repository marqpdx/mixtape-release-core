# earthlab/models/course_run.py

import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel
from earthlab.choices import CourseRunStatus, EnrollmentPolicy


class CourseRun(BaseModel):
    """
    A specific offering of a Course. Courses can be offered multiple times,
    each run with its own dates, enrollment cap, and status.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course = models.ForeignKey(
        "earthlab.Course",
        on_delete=models.CASCADE,
        related_name="runs",
    )

    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional title for this run (e.g. 'Spring 2026 Cohort')",
    )

    status = models.CharField(
        max_length=16,
        choices=CourseRunStatus.choices,
        default=CourseRunStatus.UPCOMING,
    )

    enrollment_policy = models.CharField(
        max_length=16,
        choices=EnrollmentPolicy.choices,
        default=EnrollmentPolicy.OPEN,
    )

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    max_enrollment = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Max enrollments (null = unlimited)",
    )

    class Meta:
        ordering = ["-start_date", "-created_at"]
        indexes = [
            models.Index(fields=["course", "status"]),
        ]

    def __str__(self):
        label = self.title or f"Run {self.created_at:%Y-%m-%d}"
        return f"{self.course} — {label}"
