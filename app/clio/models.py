# clio/models.py
import uuid

from django.db import models

from fundamentals.bases import BaseModel


class ClioState(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.OneToOneField(
        "profiles.UserProfile",
        on_delete=models.CASCADE,
        related_name="clio_state",
    )
    last_surfaced_at = models.DateTimeField(null=True, blank=True)
    last_surfaced_signal = models.CharField(max_length=64, blank=True)
    # 'aperture_log' | 'neglected_content' | 'recurring_action'
    last_dismissed_at = models.DateTimeField(null=True, blank=True)
    dismiss_mode = models.CharField(
        max_length=32,
        default="session",
        choices=[
            ("session", "Session"),
            ("permanent", "Permanent"),
            ("remind_later", "Remind Later"),
        ],
    )
    remind_later_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        pass

    def __str__(self):
        return f"ClioState for profile {self.profile_id}"
