import uuid
from django.db import models
from almanac.models import EventOccurrence


class BridgeSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurrence = models.OneToOneField(
        EventOccurrence,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bridge_session",
    )
    room_name = models.CharField(max_length=255, unique=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return self.room_name
