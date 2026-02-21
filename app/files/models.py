import uuid
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models

from fundamentals.bases import BaseModel


class StoredFile(BaseModel):
    """
    Canonical stored file record (S3-backed path).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, unique=True)
    file_path = models.CharField(max_length=512)
    file_name = models.CharField(max_length=255, blank=True, default="")
    file_type = models.CharField(max_length=128, blank=True, default="")
    file_size = models.BigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stored_files",
    )
    source = models.CharField(max_length=64, blank=True, default="")

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=["file_type"]),
            models.Index(fields=["uploaded_by"]),
        ]

    def __str__(self):
        return f"{self.file_name or self.file_path}"

    @property
    def url(self) -> str | None:
        if not self.file_path:
            return None
        return default_storage.url(self.file_path)
