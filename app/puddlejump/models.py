import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel


class Library(BaseModel):
    """A member's personal Puddlejump library, or a group's library."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    owner_object_id = models.UUIDField(null=True, blank=True, db_index=True)
    owner_object = GenericForeignKey('owner_content_type', 'owner_object_id')

    title = models.CharField(max_length=255, blank=True)
    slug = models.SlugField(max_length=255, unique=True, null=True, blank=True)
    summary = models.TextField(blank=True)
    body = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Library'
        verbose_name_plural = 'Libraries'

    def __str__(self):
        return self.title or f'Library {self.id}'

    @property
    def file_count(self):
        return self.items.filter(is_folder=False).count()

    @property
    def total_size_bytes(self):
        return sum(
            item.size_bytes
            for item in self.items.filter(is_folder=False)
            if item.size_bytes is not None
        )


class LibraryItem(BaseModel):
    """A single item (file or folder) within a Library."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(
        Library,
        on_delete=models.CASCADE,
        related_name='items',
    )

    is_folder = models.BooleanField(default=False)
    title = models.CharField(max_length=255, blank=True)
    folder_path = models.CharField(max_length=500, blank=True)
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False)
    order_index = models.IntegerField(default=0)

    # MIME type string — named to avoid shadowing Django's ContentType FK
    content_type_str = models.CharField(max_length=100, blank=True)
    # ID of the linked content object
    content_id = models.UUIDField(null=True, blank=True)

    filename = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    hash_sha256 = models.CharField(max_length=64, blank=True)
    s3_key = models.TextField(blank=True)

    # FK to files app's stored file
    source_file_id = models.UUIDField(null=True, blank=True)
    current_version = models.ForeignKey(
        'LibraryItemVersion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        ordering = ['order_index']
        indexes = [
            models.Index(fields=['library', 'order_index']),
            models.Index(fields=['library', 'is_folder']),
        ]

    def __str__(self):
        return self.title or f'LibraryItem {self.id}'


class LibraryItemVersion(BaseModel):
    """Immutable version record for a single file upload. Parent-linked for history traversal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_item = models.ForeignKey(LibraryItem, on_delete=models.CASCADE, related_name='versions')
    parent_version = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    hash_sha256 = models.CharField(max_length=64)
    seaweed_key = models.TextField()  # puddlejump/{library_id}/{version_id}/{filename}
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Version {self.id} of {self.library_item_id}'


class ManifestEvent(BaseModel):
    """Append-only log of every mutation to a library's file manifest."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name='manifest_events')
    event_type = models.CharField(max_length=50)  # 'upload', 'delete', 'rename', 'restore'
    library_item = models.ForeignKey(
        LibraryItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='manifest_events',
    )
    version = models.ForeignKey(
        LibraryItemVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name='manifest_events',
    )
    path = models.TextField()
    hash_sha256 = models.CharField(max_length=64, blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'ManifestEvent {self.event_type} on {self.library_id} at {self.created_at}'


class SnapshotConfig(BaseModel):
    """Per-library snapshot configuration — frequency, destination, retention."""

    library = models.OneToOneField(Library, on_delete=models.CASCADE, related_name='snapshot_config')
    is_enabled = models.BooleanField(default=False)
    frequency = models.CharField(max_length=20, default='weekly')  # 'weekly', 'daily', 'hourly', 'on_transaction'
    endpoint_type = models.CharField(max_length=20, default='internal')  # 'internal', 's3', 'nas'
    endpoint_url = models.TextField(blank=True)
    endpoint_credentials = models.JSONField(default=dict, blank=True)
    retain_count = models.IntegerField(default=4)
    last_snapshot_at = models.DateTimeField(null=True, blank=True)
    tier = models.CharField(max_length=20, default='standard')  # 'standard', 'premium'

    class Meta:
        verbose_name = 'Snapshot Config'

    def __str__(self):
        return f'SnapshotConfig for {self.library_id}'


class LibrarySnapshot(BaseModel):
    """Immutable point-in-time snapshot of a library's file manifest."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name='snapshots')
    snapshot_at = models.DateTimeField()
    manifest_json = models.JSONField()
    file_count = models.IntegerField()
    total_size_bytes = models.BigIntegerField()
    delivered_to = models.CharField(max_length=20)  # 'internal', 's3', 'nas'
    delivery_key = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending')  # 'pending', 'complete', 'failed'

    class Meta:
        ordering = ['-snapshot_at']

    def __str__(self):
        return f'LibrarySnapshot {self.id} at {self.snapshot_at}'
