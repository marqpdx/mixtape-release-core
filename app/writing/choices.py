# writing/choices.py
from django.db import models

class ContentStatus(models.TextChoices):
    DRAFT     = "draft",     "Draft"
    PUBLISHED = "published", "Published"
    SCHEDULED = "scheduled", "Scheduled"  # include if you support scheduling
    ARCHIVED  = "archived",  "Archived"
    DELETED   = "deleted",   "Deleted"
