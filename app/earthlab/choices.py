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
