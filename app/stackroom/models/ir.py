# stackroom/models/ir.py

from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from fundamentals.models import BaseContent

# User = settings.AUTH_USER_MODEL


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Library(BaseContent):
    """
    Document library with polymorphic sponsorship.

    Inherits from BaseContent:
    - id (UUID)
    - title (the library name)
    - slug (auto-generated from title, unique per sponsor)
    - summary (short description)
    - body (detailed description/purpose)
    - sponsor (GenericFK to Group or User)
    - author, submitted_by
    - created_at, updated_at

    Puddlejump fields (for bundle import/export):
    - puddlejump_bundle_id (UUID from imported bundle)
    - puddlejump_origin (imported vs created in Mixtape)
    - puddlejump_exported_at (timestamp of last export)
    """

    # Puddlejump bundle tracking
    puddlejump_bundle_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text='UUID from puddlejump.json manifest (if imported from bundle)'
    )
    puddlejump_origin = models.CharField(
        max_length=20,
        choices=[
            ('imported', 'Imported from Puddlejump'),
            ('created', 'Created in Mixtape')
        ],
        default='created',
        help_text='Whether this collection was imported from a Puddlejump bundle or created in Mixtape'
    )
    puddlejump_exported_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Timestamp of last Puddlejump bundle export'
    )

    class Meta(BaseContent.Meta):
        constraints = BaseContent.Meta.constraints + [
            # Unique library title per sponsor
            models.UniqueConstraint(
                fields=['sponsor_content_type', 'sponsor_object_id', 'title'],
                name='unique_library_title_per_sponsor'
            )
        ]
        verbose_name = "Library"
        verbose_name_plural = "Libraries"

    def __str__(self) -> str:
        sponsor_name = getattr(
            self.sponsor,
            'title',
            getattr(self.sponsor, 'display_name', str(self.sponsor))
        )
        return f"{sponsor_name} — {self.title}"


class LibraryItem(TimeStamped):
    """
    Editorial overlay for Library curation.

    Represents how content appears within a Collection (Library in Collection role).
    Content can be:
    - SourceFile (PDFs, videos, audio, images - hard files)
    - WritingPiece (published articles, posts, collaborative docs, announcements)
    - Folder (organizational container with title and summary)

    Stores ordering, hierarchy, tags, and curatorial intent WITHOUT mutating source truth.

    Key invariants:
    - Reordering a LibraryItem NEVER reorders Shards or Chunks
    - Editing metadata NEVER triggers re-ingestion
    - Deleting a LibraryItem NEVER deletes the content object
    - Folders (is_folder=True) cannot have content_type/content_object_id
    - Non-folders must have content_type/content_object_id
    - Max nesting depth: 3 levels (root → section → subsection)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name="items")

    # Folder support
    is_folder = models.BooleanField(
        default=False,
        help_text="True if this is an organizational folder, not actual content"
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Folder name (only used when is_folder=True)"
    )

    # Polymorphic content reference (SourceFile | WritingPiece)
    # Nullable for folders (is_folder=True)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    content_object_id = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'content_object_id')

    # Hierarchy (parent-child relationships for nesting)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        help_text="Parent folder for nesting (max 3 levels)"
    )

    # Editorial ordering (user-controlled, within parent or root)
    order_index = models.IntegerField(default=0)

    # Virtual hierarchy (legacy - keeping for backwards compatibility)
    # TODO: Consider deprecating in favor of parent/children
    folder_path = models.CharField(max_length=500, blank=True, default="")

    # Curatorial metadata
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")

    # Puddlejump canonical metadata (cached from file front matter)
    puddlejump_canonical_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Canonical metadata from file front matter (cached): canonical_date, canonical_authority, supersedes, review_date'
    )

    # Display flags
    is_featured = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ['order_index', 'created_at']
        indexes = [
            models.Index(fields=['library', 'order_index']),
            models.Index(fields=['library', 'parent']),  # Fast hierarchy queries
            models.Index(fields=['library', 'is_folder']),
            models.Index(fields=['library', 'folder_path']),  # Legacy support
            models.Index(fields=['content_type', 'content_object_id']),  # Fast polymorphic lookups
        ]
        constraints = [
            # Content can appear multiple times in a Library (different contexts)
            # but each appearance needs unique position within its parent
            # NOTE: This constraint only applies to non-folders
            # Folders are uniquely identified by library + parent + title + order_index
            models.UniqueConstraint(
                fields=['library', 'content_type', 'content_object_id', 'order_index'],
                name='unique_library_item_position_root',
                condition=models.Q(is_folder=False, parent__isnull=True),
            ),
            models.UniqueConstraint(
                fields=['library', 'parent', 'content_type', 'content_object_id', 'order_index'],
                name='unique_library_item_position_child',
                condition=models.Q(is_folder=False, parent__isnull=False),
            ),
        ]

    def clean(self):
        """
        Validate LibraryItem constraints.

        Enforces:
        1. Folders cannot have content_type/content_object_id
        2. Non-folders must have content_type/content_object_id
        3. Max nesting depth of 3 levels
        4. Folders cannot be nested under non-folders
        5. Collections cannot link to themselves (circular reference prevention)
        6. Collections cannot create circular chains (A->B->A)
        """
        from django.core.exceptions import ValidationError

        # Rule 1: Folders cannot have content
        if self.is_folder and (self.content_type is not None or self.content_object_id is not None):
            raise ValidationError(
                "Folders (is_folder=True) cannot have content_type or content_object_id. "
                "Remove the content reference or set is_folder=False."
            )

        # Rule 2: Non-folders must have content (except Puddlejump placeholders)
        # Puddlejump Phase 2 creates placeholder items without content refs
        # Phase 3 will create SourceFiles and link them
        is_puddlejump_placeholder = (
            self.library and
            self.library.puddlejump_origin == 'imported'
        )

        if not self.is_folder and not is_puddlejump_placeholder:
            if self.content_type is None or self.content_object_id is None:
                raise ValidationError(
                    "Non-folder items must have both content_type and content_object_id. "
                    "Either provide content or set is_folder=True."
                )

        # Rule 3: Check nesting depth (max 3 levels: root, section, subsection)
        if self.parent:
            depth = 1
            current = self.parent
            while current is not None:
                depth += 1
                if depth > 3:
                    raise ValidationError(
                        "Maximum nesting depth is 3 levels (root → section → subsection). "
                        "This item would create a 4th level."
                    )
                current = current.parent

        # Rule 4: Items can only be nested under folders
        if self.parent and not self.parent.is_folder:
            raise ValidationError(
                f"Items can only be nested under folders. "
                f"Parent item '{self.parent}' is not a folder (is_folder=False)."
            )

        # Rule 5 & 6: Collection linking validation (circular reference prevention)
        if not self.is_folder and self.content_type and self.content_type.model == 'library':
            # Prevent self-linking
            if str(self.content_object_id) == str(self.library.id):
                raise ValidationError(
                    "Collection cannot link to itself. "
                    f"Attempted to link collection '{self.library.title}' to itself."
                )

            # Prevent circular chains (A->B->C->A)
            # Check if the target collection links back to this collection (directly or indirectly)
            self._check_circular_collection_links(
                target_collection_id=self.content_object_id,
                original_collection_id=self.library.id,
                visited=set()
            )

    def _check_circular_collection_links(self, target_collection_id, original_collection_id, visited, max_depth=10):
        """
        Recursively check if linking to target_collection_id would create a circular reference.

        Args:
            target_collection_id: The collection we're trying to link to
            original_collection_id: The original collection (to detect cycles)
            visited: Set of already visited collection IDs (to prevent infinite loops)
            max_depth: Safety limit for recursion depth

        Raises:
            ValidationError: If circular reference detected
        """
        from django.core.exceptions import ValidationError

        # Safety check: prevent excessive recursion
        if len(visited) >= max_depth:
            raise ValidationError(
                f"Collection linking depth exceeds maximum ({max_depth}). "
                "This may indicate a circular reference or excessively deep linking chain."
            )

        # If we've seen this collection before, we have a cycle
        if target_collection_id in visited:
            return

        visited.add(target_collection_id)

        # Get all LibraryItems in the target collection that link to other collections
        linked_collections = LibraryItem.objects.filter(
            library_id=target_collection_id,
            is_folder=False,
            content_type__model='library'
        ).values_list('content_object_id', flat=True)

        for linked_id in linked_collections:
            # If any linked collection points back to our original collection, we have a cycle
            if str(linked_id) == str(original_collection_id):
                raise ValidationError(
                    f"Circular collection reference detected. "
                    f"Linking would create a cycle in the collection chain."
                )

            # Recursively check the linked collection
            self._check_circular_collection_links(
                target_collection_id=linked_id,
                original_collection_id=original_collection_id,
                visited=visited.copy(),
                max_depth=max_depth
            )

    def save(self, *args, **kwargs):
        """Override save to run validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        if self.is_folder:
            return f"📁 {self.title or 'Untitled Folder'}"

        # Special handling for collection links
        if self.content_type and self.content_type.model == 'library':
            return f"{self.library.title} → 🔗 {self.content_object} (#{self.order_index})"

        content_desc = str(self.content_object) if self.content_object else f"{self.content_type.model}#{self.content_object_id}"
        return f"{self.library.title} → {content_desc} (#{self.order_index})"


class SourceFile(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    library = models.ForeignKey(Library, on_delete=models.CASCADE, related_name="source_files")

    origin = models.CharField(max_length=20)  # "upload" | "git" | "external" | "audio"
    path = models.TextField()                # repo path or storage key
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0, validators=[MinValueValidator(0)])
    hash_sha256 = models.CharField(max_length=64)

    git_commit = models.CharField(max_length=64, null=True, blank=True)
    source_url = models.TextField(null=True, blank=True)

    # created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    ir_version = models.CharField(max_length=32, default="0.1")

    class Meta:
        constraints = [
            # Phase 0 contract: SourceFile identity = (library + hash)
            models.UniqueConstraint(fields=["library", "hash_sha256"], name="uniq_sourcefile_library_hash"),
        ]


class IngestionRun(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name="ingestion_runs")

    status = models.CharField(max_length=20, default="pending")  # pending|running|success|partial|failed
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # optional counters (denormalized convenience)
    artifacts_created = models.IntegerField(default=0)
    shards_extracted = models.IntegerField(default=0)
    chunks_indexed = models.IntegerField(default=0)

    # store errors/warnings here or in Receipt; keeping simple:
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)

    def __str__(self) -> str:
        return f"Run {self.id} ({self.status})"


class Artifact(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_file = models.ForeignKey(SourceFile, on_delete=models.CASCADE, related_name="artifacts")

    artifact_uid = models.CharField(max_length=128)

    artifact_type = models.CharField(max_length=40)  # extracted_text | normalized_markdown | transcript_text | ...
    format = models.CharField(max_length=64, default="text/plain")
    text = models.TextField(null=True, blank=True)          # ok for Phase 1
    storage_key = models.TextField(null=True, blank=True)   # later

    ir_version = models.CharField(max_length=32, default="0.1")

    # Extractive metadata for Simple Search (non-editable, programmatically generated)
    interior_summary = models.TextField(
        blank=True,
        default='',
        help_text='Extractive summary (2-3 sentences from original text, ~300-500 chars) for fast search'
    )
    keywords = models.JSONField(
        default=list,
        help_text='Top 12 keywords extracted via TF-IDF or RAKE (array of strings)'
    )
    metadata_version = models.CharField(
        max_length=32,
        default='',
        blank=True,
        help_text='Version of extraction logic used (e.g., "1.0-tfidf" or "1.1-inkwell")'
    )

    class Meta:
        indexes = [
            models.Index(fields=["source_file", "artifact_type"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["source_file", "artifact_uid"], name="uniq_artifact_uid_per_source"),
        ]


class Shard(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="shards")

    kind = models.CharField(max_length=40)  # heading|paragraph|list|table|code|...
    level = models.IntegerField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    text = models.TextField(null=True, blank=True)

    order_index = models.IntegerField()

    parent_shard = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)

    # provenance span
    span = models.JSONField(default=dict)  # {char_start, char_end, line_start?, page_start?, ...}

    class Meta:
        indexes = [
            models.Index(fields=["artifact", "order_index"]),
        ]


class Chunk(TimeStamped):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    artifact = models.ForeignKey(Artifact, on_delete=models.CASCADE, related_name="chunks")

    chunk_strategy = models.CharField(max_length=40, default="sliding_window")
    text = models.TextField()

    token_estimate = models.IntegerField(default=0)
    order_index = models.IntegerField()

    source_spans = models.JSONField(default=list)  # locked contract structure
    hash_sha256 = models.CharField(max_length=64)
    ir_version = models.CharField(max_length=32, default="0.1")

    # link to vector store point id (string; usually chunk UUID)
    embedding_id = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        constraints = [
            # Phase 0 contract: Chunk identity = (artifact + strategy + hash + ir_version)
            models.UniqueConstraint(
                fields=["artifact", "chunk_strategy", "hash_sha256", "ir_version"],
                name="uniq_chunk_identity",
            )
        ]
        indexes = [
            models.Index(fields=["artifact", "order_index"]),
        ]


class IngestionReceipt(TimeStamped):
    """
    Append-only receipts per run.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(IngestionRun, on_delete=models.CASCADE, related_name="receipts")

    status = models.CharField(max_length=20)  # success|partial|failed
    payload = models.JSONField(default=dict)

    class Meta:
        indexes = [models.Index(fields=["run", "created_at"])]
from django.db import models

# Create your models here.
