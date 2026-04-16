import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from fundamentals.bases import BaseModel
from fundamentals.models import BaseContent


class Collection(BaseContent):
    """
    A curated gathering of content items.

    Django-native curation layer. Canonical data lives here; Stackroom is the
    derived IR layer ingested asynchronously via the CollectionStackroomAdapter.

    Sponsor (group or user) owns the collection. Visibility controls access.
    Items are managed via CollectionItem.
    """

    VISIBILITY_CHOICES = [
        ('public', 'Public'),
        ('unlisted', 'Unlisted'),
        ('members', 'Members'),
        ('private', 'Private'),
    ]

    SCOPE_CHOICES = [
        ('writing', 'Writing'),
        ('audio', 'Audio'),
        ('course', 'Course'),
        ('general', 'General'),
    ]

    visibility = models.CharField(
        max_length=20,
        choices=VISIBILITY_CHOICES,
        default='private',
    )
    scope = models.CharField(
        max_length=50,
        choices=SCOPE_CHOICES,
        default='general',
    )

    class Meta(BaseContent.Meta):
        verbose_name = 'Collection'
        verbose_name_plural = 'Collections'

    def __str__(self):
        return self.title or f'Collection {self.id}'


class CollectionItem(BaseModel):
    """
    An item within a Collection.

    Editorial overlay — records what is in the collection, in what order, and
    with what curatorial metadata. Does not own the underlying content.

    Supports hierarchy (folders) via self-referential parent FK.
    """

    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name='items',
    )

    # Polymorphic content reference (null for folder items)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    content_object_id = models.UUIDField(null=True, blank=True, db_index=True)
    content_object = GenericForeignKey('content_type', 'content_object_id')

    # Folder support — folders have is_folder=True, no content reference
    is_folder = models.BooleanField(default=False)
    title = models.CharField(max_length=255, blank=True)  # folder name or display override

    # Hierarchy
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
    )

    # Editorial ordering (user-controlled)
    order_index = models.IntegerField(default=0)

    # Curatorial metadata
    folder_path = models.CharField(max_length=500, blank=True)
    section_title = models.CharField(max_length=255, blank=True)
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    is_featured = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)

    class Meta(BaseModel.Meta):
        ordering = ['order_index']
        indexes = [
            models.Index(fields=['collection', 'order_index']),
            models.Index(fields=['collection', 'parent']),
            models.Index(fields=['collection', 'is_folder']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['collection', 'content_type', 'content_object_id', 'order_index'],
                condition=models.Q(is_folder=False, parent__isnull=True),
                name='unique_collection_item_position_root',
            ),
        ]

    def __str__(self):
        if self.is_folder:
            return f'[folder] {self.title}'
        return f'CollectionItem {self.id}'
