# assets/models.py

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
import uuid

from fundamentals.bases import BaseModel
class AssetType(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"
    DOCUMENT = "document", "Document"
    AUDIO = "audio", "Audio"
    OTHER = "other", "Other"

PRIVACY_CHOICES = [
    ("public", "Public"),
    ("partners", "Partners Only"),
    ("members", "Group Members Only"),
    ("admins", "Admins Only"),
]

class Asset(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=50)  # e.g. image, video, document

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()  # Group or UserProfile UUID
    linked_object = GenericForeignKey("content_type", "object_id")

    file_path = models.CharField(max_length=255)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=100)
    file_size = models.BigIntegerField(null=True, blank=True)
    folder_path = models.CharField(max_length=500, blank=True, null=True)

    upload_status = models.CharField(
        max_length=20,
        choices=[
            ("queued", "Queued"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="queued",
    )

    privacy = models.CharField(
        max_length=20,
        choices=PRIVACY_CHOICES,
        default="members",
    )

class ImageFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="image_fields")
    exif_data = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"ImageFields for {self.asset.file_name}"


class VideoFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="video_fields")
    duration = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"VideoFields for {self.asset.file_name}"


class DocumentFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="document_fields")
    page_count = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"DocumentFields for {self.asset.file_name}"


class AudioFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="audio_fields")
    duration = models.FloatField(null=True, blank=True)
    bitrate = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"AudioFields for {self.asset.file_name}"


class OtherFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name="other_fields")
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"OtherFields for {self.asset.file_name}"


# Join Tables:

class BaseAssetFields(models.Model):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        abstract = True

class GroupAsset(BaseAssetFields):
    group = models.ForeignKey("groups.Group", on_delete=models.CASCADE, related_name="group_assets")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_group_assets"
    )
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)

class ProfileAsset(BaseAssetFields):
    profile = models.ForeignKey("profiles.UserProfile", on_delete=models.CASCADE, related_name="profile_assets")

# class CollectionAsset(BaseAssetFields):
#     collection = models.ForeignKey("library.Collection", on_delete=models.CASCADE, related_name="collection_assets")


    # see README-assets.md

class AssetUsage(BaseModel):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name="usages")

    # Polymorphic content attachment
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    role = models.CharField(max_length=100, blank=True)  # e.g. 'cover_image', 'inline_image'
    caption = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return f"{self.asset} used in {self.content_object} as {self.role or 'unspecified role'}"
