# earthlab/choices.py

from django.db import models


class CourseStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class LessonStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class DifficultyLevel(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    INTERMEDIATE = "intermediate", "Intermediate"
    ADVANCED = "advanced", "Advanced"


class DeliveryType(models.TextChoices):
    ONLINE = "online", "Online"
    SELF_PACED = "self_paced", "Self-Paced"
    HYBRID = "hybrid", "Hybrid"
    IN_PERSON = "in_person", "In Person"


class CourseRunStatus(models.TextChoices):
    UPCOMING = "upcoming", "Upcoming"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ARCHIVED = "archived", "Archived"


class EnrollmentPolicy(models.TextChoices):
    OPEN = "open", "Open"
    INVITE = "invite", "Invite Only"
    CLOSED = "closed", "Closed"


class EnrollmentStatus(models.TextChoices):
    ENROLLED = "enrolled", "Enrolled"
    COMPLETED = "completed", "Completed"
    DROPPED = "dropped", "Dropped"
    WAITLISTED = "waitlisted", "Waitlisted"


class ProgressStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
