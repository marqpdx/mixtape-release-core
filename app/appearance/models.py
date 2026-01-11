from django.db import models

from fundamentals.bases import BaseModel
from groups.models import Group


class GroupThemeSettings(BaseModel):
    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="theme_settings",
    )
    hidden_theme_ids = models.JSONField(default=list, blank=True)
    group_themes = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"Theme settings for {self.group.title}"

# Create your models here.
