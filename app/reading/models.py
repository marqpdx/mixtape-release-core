import uuid

from django.db import models

from fundamentals.bases import BaseModel


class Dart(BaseModel):
    ANCHOR_SELECTION = "selection"
    ANCHOR_DOCUMENT = "document"
    ANCHOR_CHOICES = [
        (ANCHOR_SELECTION, "Selection"),
        (ANCHOR_DOCUMENT, "Document"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="darts",
    )
    artifact = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="darts",
    )
    anchor_type = models.CharField(max_length=20, choices=ANCHOR_CHOICES, default=ANCHOR_SELECTION)
    selected_text = models.TextField(blank=True, null=True)
    anchor_start_offset = models.IntegerField(default=0)
    anchor_end_offset = models.IntegerField(default=0)
    note_text = models.TextField(blank=True, default="")
    is_flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "artifact"]),
            models.Index(fields=["artifact"]),
        ]

    def __str__(self):
        return f"Dart by {self.user_id} on {self.artifact_id} ({self.anchor_type})"


class ReadingStats(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="reading_stats",
    )
    artifact = models.ForeignKey(
        "writing.WritingPiece",
        on_delete=models.CASCADE,
        related_name="reading_stats",
    )
    first_read_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    times_read = models.IntegerField(default=0)
    flagged_to_reread = models.BooleanField(default=False)

    class Meta:
        unique_together = [("user", "artifact")]
        indexes = [
            models.Index(fields=["user", "artifact"]),
        ]

    def __str__(self):
        return f"ReadingStats: {self.user_id} / {self.artifact_id}"
