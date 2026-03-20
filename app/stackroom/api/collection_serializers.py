# stackroom/api/collection_serializers.py

"""
Collection API Serializers

These serializers focus on the CURATION layer (Collection role of Library).
They are separate from Stackroom serializers (IR/retrieval layer) to maintain
the conceptual boundary between truth and meaning.

Stackroom serializers → what exists, how to retrieve it (truth)
Collection serializers → how to present it, how to organize it (meaning)
"""

from rest_framework import serializers
from stackroom.models import Library, LibraryItem, SourceFile


class CollectionListSerializer(serializers.Serializer):
    """
    Lightweight serializer for listing Collections.
    Used in browse/search contexts where full detail is unnecessary.
    """
    id = serializers.UUIDField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    slug = serializers.CharField()

    # Sponsor info (flattened)
    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()

    # Counts
    item_count = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    # Timestamps
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_sponsor_type(self, obj):
        """Map sponsor_content_type to user-friendly string"""
        if obj.sponsor_content_type.model == 'group':
            return 'group'
        elif obj.sponsor_content_type.model == 'user':
            return 'user'
        return 'unknown'

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_sponsor_name(self, obj):
        sponsor = obj.sponsor
        return getattr(sponsor, 'title', getattr(sponsor, 'display_name', str(sponsor)))

    def get_item_count(self, obj):
        """Number of curated items"""
        return obj.items.count()

    def get_file_count(self, obj):
        """Number of raw source files (may differ from item_count)"""
        return obj.source_files.count()


class CollectionDetailSerializer(serializers.Serializer):
    """
    Full Collection detail including narrative metadata.
    Does NOT include items (use separate endpoint for items list).
    """
    id = serializers.UUIDField()
    title = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    slug = serializers.CharField()

    # Sponsor info
    sponsor_type = serializers.SerializerMethodField()
    sponsor_id = serializers.SerializerMethodField()
    sponsor_name = serializers.SerializerMethodField()

    # Author info (from BaseContent)
    author_name = serializers.CharField(allow_blank=True)
    submitted_by = serializers.SerializerMethodField()

    # Counts and status
    item_count = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()
    ingestion_status = serializers.SerializerMethodField()

    # Timestamps
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_sponsor_type(self, obj):
        if obj.sponsor_content_type.model == 'group':
            return 'group'
        elif obj.sponsor_content_type.model == 'user':
            return 'user'
        return 'unknown'

    def get_sponsor_id(self, obj):
        return str(obj.sponsor_object_id)

    def get_sponsor_name(self, obj):
        sponsor = obj.sponsor
        return getattr(sponsor, 'title', getattr(sponsor, 'display_name', str(sponsor)))

    def get_submitted_by(self, obj):
        if obj.submitted_by:
            return {
                'id': str(obj.submitted_by.id),
                'username': obj.submitted_by.username,
                'display_name': getattr(obj.submitted_by, 'display_name', obj.submitted_by.username)
            }
        return None

    def get_item_count(self, obj):
        return obj.items.count()

    def get_file_count(self, obj):
        return obj.source_files.count()

    def get_ingestion_status(self, obj):
        """Summary of ingestion progress (hybrid concern)"""
        from stackroom.models import IngestionRun

        total_files = obj.source_files.count()
        if total_files == 0:
            return {
                'total': 0,
                'ready': 0,
                'processing': 0,
                'pending': 0,
                'failed': 0,
            }

        # Get latest run per file (Postgres DISTINCT ON)
        runs = (
            IngestionRun.objects.filter(source_file__library=obj)
            .order_by('source_file', '-created_at')
            .distinct('source_file')
        )

        status_counts = {
            'total': total_files,
            'ready': runs.filter(status='success').count(),
            'processing': runs.filter(status__in=['pending', 'running']).count(),
            'failed': runs.filter(status='failed').count(),
        }
        status_counts['pending'] = total_files - runs.count()

        return status_counts


class LibraryItemSerializer(serializers.Serializer):
    """
    Serializer for LibraryItem (editorial overlay).
    Handles polymorphic content (SourceFile | WritingPiece).
    """
    id = serializers.UUIDField()
    title = serializers.CharField(allow_blank=True)
    order_index = serializers.IntegerField()
    folder_path = serializers.CharField(allow_blank=True)
    parent_id = serializers.SerializerMethodField()
    tags = serializers.JSONField()
    notes = serializers.CharField(allow_blank=True)
    is_featured = serializers.BooleanField()
    is_hidden = serializers.BooleanField()

    # Polymorphic content
    content_type = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()

    # Timestamps
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_parent_id(self, obj):
        """Return parent ID for tree structure (null for root items)"""
        return str(obj.parent_id) if obj.parent_id else None

    def get_content_type(self, obj):
        """Return 'source_file' | 'writing_piece' | 'collection'"""
        model_name = obj.content_type.model
        if model_name == 'sourcefile':
            return 'source_file'
        elif model_name == 'writingpiece':
            return 'writing_piece'
        elif model_name == 'library':
            return 'collection'
        return model_name

    def get_content(self, obj):
        """Return type-specific content representation"""
        content_obj = obj.content_object

        if not content_obj:
            return None

        # SourceFile representation
        if obj.content_type.model == 'sourcefile':
            return {
                'id': str(content_obj.id),
                'filename': content_obj.filename,
                'content_type': content_obj.content_type,
                'size_bytes': content_obj.size_bytes,
                'origin': content_obj.origin,
                'created_at': content_obj.created_at.isoformat(),
            }

        # WritingPiece representation
        elif obj.content_type.model == 'writingpiece':
            return {
                'id': str(content_obj.id),
                'title': content_obj.title,
                'slug': content_obj.slug,
                'summary': content_obj.summary,
                'writing_kind': content_obj.writing_kind,  # dispatch | article | post | announcement
                'status': content_obj.status,
                'author_name': content_obj.author_name,
                'published_at': content_obj.published_at.isoformat() if content_obj.published_at else None,
                'created_at': content_obj.created_at.isoformat(),
            }

        # Collection (Library) representation - for linked collections
        elif obj.content_type.model == 'library':
            return {
                'id': str(content_obj.id),
                'title': content_obj.title,
                'slug': content_obj.slug,
                'summary': content_obj.summary,
                'item_count': content_obj.items.count(),
                'file_count': content_obj.source_files.count(),
                'sponsor_type': 'group' if content_obj.sponsor_content_type.model == 'group' else 'user',
                'created_at': content_obj.created_at.isoformat(),
            }

        return None


class LibraryItemCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new LibraryItem (polymorphic).
    Supports SourceFile, WritingPiece, and Collection (linking).
    """
    content_type = serializers.ChoiceField(
        choices=['source_file', 'writing_piece', 'collection'],
        help_text="Type of content to add (collection = link to another collection)"
    )
    content_id = serializers.UUIDField(help_text="ID of content object (SourceFile, WritingPiece, or Collection)")
    order_index = serializers.IntegerField(required=False, help_text="Position in Collection (auto if not provided)")
    folder_path = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    is_featured = serializers.BooleanField(required=False, default=False)


class LibraryItemUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating an existing LibraryItem.
    All fields optional (PATCH semantics).
    """
    order_index = serializers.IntegerField(required=False)
    folder_path = serializers.CharField(max_length=500, required=False, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_featured = serializers.BooleanField(required=False)
    is_hidden = serializers.BooleanField(required=False)


class LibraryItemBulkReorderSerializer(serializers.Serializer):
    """
    Serializer for bulk reordering and nesting items.

    Client sends array of {id, order_index, parent_id?} objects.
    Supports both reordering (changing order_index) and nesting (changing parent).
    """
    items = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        help_text="Array of {id: uuid, order_index: int, parent_id?: uuid|null}"
    )

    def validate_items(self, value):
        """Ensure each item has required fields"""
        for item in value:
            if 'id' not in item or 'order_index' not in item:
                raise serializers.ValidationError(
                    "Each item must have 'id' and 'order_index'"
                )
            # parent_id is optional - can be null (move to root) or uuid (nest under folder)
        return value


class CollectionCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a new Collection (Library).
    """
    title = serializers.CharField(max_length=255, required=True)
    summary = serializers.CharField(required=False, allow_blank=True, default='')
    body = serializers.CharField(required=False, allow_blank=True, default='')
    sponsor_type = serializers.ChoiceField(choices=['group', 'user'], required=True)
    sponsor_id = serializers.UUIDField(required=True)
    author_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    visibility = serializers.ChoiceField(
        choices=['public', 'members', 'unlisted', 'private'],
        required=False,
        default='private',
    )


class CollectionUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating Collection metadata.
    All fields optional (PATCH semantics).
    """
    title = serializers.CharField(max_length=255, required=False)
    summary = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    author_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=['public', 'members', 'unlisted', 'private'],
        required=False,
    )


class SourceFileMinimalSerializer(serializers.Serializer):
    """
    Minimal SourceFile info for browsing available files.
    """
    id = serializers.UUIDField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    origin = serializers.CharField()
    created_at = serializers.DateTimeField()

    # Indicate if already added to Collection
    in_collection = serializers.BooleanField(default=False)
    item_count = serializers.IntegerField(default=0)  # How many times added


class WritingPieceMinimalSerializer(serializers.Serializer):
    """
    Minimal WritingPiece info for browsing available documents.
    """
    id = serializers.UUIDField()
    title = serializers.CharField()
    slug = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    writing_kind = serializers.CharField()  # dispatch | article | post | announcement
    status = serializers.CharField()
    author_name = serializers.CharField(allow_blank=True)
    published_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()

    # Indicate if already added to Collection
    in_collection = serializers.BooleanField(default=False)
    item_count = serializers.IntegerField(default=0)  # How many times added


class CollectionFileUploadSerializer(serializers.Serializer):
    """
    Serializer for uploading files directly to a Collection.

    This creates SourceFile only - NO immediate ingestion.
    Ingestion happens asynchronously via background task.
    """
    file = serializers.FileField(help_text="File to upload")


class CollectionFileUploadResponseSerializer(serializers.Serializer):
    """
    Response from Collection file upload.
    Returns minimal info - no ingestion_run_id since ingestion is deferred.
    """
    source_file_id = serializers.UUIDField()
    filename = serializers.CharField()
    status = serializers.CharField()


# Import models here to avoid circular import
from django.db import models
