# earthlab/models/enrollment.py

import uuid

from django.conf import settings
from django.db import models

from fundamentals.bases import BaseModel
from earthlab.choices import EnrollmentStatus


class Enrollment(BaseModel):
    """
    A user's enrollment in a specific CourseRun.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    course_run = models.ForeignKey(
        "earthlab.CourseRun",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="earthlab_enrollments",
    )

    status = models.CharField(
        max_length=16,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.ENROLLED,
    )

    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-enrolled_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course_run", "user"],
                name="unique_enrollment_per_run",
            ),
        ]
        indexes = [
            models.Index(fields=["course_run", "status"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.course_run} ({self.status})"
