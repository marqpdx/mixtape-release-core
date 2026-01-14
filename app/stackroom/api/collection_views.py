# stackroom/api/collection_views.py

"""
Collection API Views

These views handle the CURATION layer (Collection role of Library).
They are conceptually separate from Stackroom views (IR/retrieval layer).

Stackroom APIs → ingestion, retrieval, truth
Collection APIs → curation, ordering, meaning

The separation is intentional and should be preserved.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction, models

from stackroom.models import Library, LibraryItem, SourceFile
from stackroom.api.collection_serializers import (
    CollectionListSerializer,
    CollectionDetailSerializer,
    CollectionCreateSerializer,
    CollectionUpdateSerializer,
    LibraryItemSerializer,
    LibraryItemCreateSerializer,
    LibraryItemUpdateSerializer,
    LibraryItemBulkReorderSerializer,
    SourceFileMinimalSerializer,
    WritingPieceMinimalSerializer,
    CollectionFileUploadSerializer,
    CollectionFileUploadResponseSerializer,
)


class CollectionListView(APIView):
    """
    GET /api/collections/ - List all Collections
    POST /api/collections/ - Create a new Collection

    List all Collections accessible to the current user.
    Query params:
    - sponsor_type: filter by 'group' or 'user'
    - sponsor_id: filter by sponsor UUID
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List all Collections accessible to user"""
        libraries = Library.objects.all().order_by('-created_at')

        # Filter by sponsor type if provided
        sponsor_type = request.query_params.get('sponsor_type')
        if sponsor_type:
            from django.contrib.contenttypes.models import ContentType
            if sponsor_type == 'group':
                from groups.models import Group
                ct = ContentType.objects.get_for_model(Group)
                libraries = libraries.filter(sponsor_content_type=ct)
            elif sponsor_type == 'user':
                from django.contrib.auth import get_user_model
                User = get_user_model()
                ct = ContentType.objects.get_for_model(User)
                libraries = libraries.filter(sponsor_content_type=ct)

        # Filter by sponsor ID if provided
        sponsor_id = request.query_params.get('sponsor_id')
        if sponsor_id:
            libraries = libraries.filter(sponsor_object_id=sponsor_id)

        # TODO: Filter by user access permissions

        serializer = CollectionListSerializer(libraries, many=True)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def post(self, request):
        """
        Create a new Collection (Library).

        Body:
        {
          "title": "Collection Title",
          "summary": "Optional summary",
          "body": "Optional detailed description",
          "sponsor_type": "group" or "user",
          "sponsor_id": "UUID",
          "author_name": "Optional author name",
          "is_featured": false (optional)
        }
        """
        serializer = CollectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Get sponsor content type
        from django.contrib.contenttypes.models import ContentType
        if data['sponsor_type'] == 'group':
            from groups.models import Group
            sponsor_ct = ContentType.objects.get_for_model(Group)
            sponsor_obj = get_object_or_404(Group, id=data['sponsor_id'])
        else:  # user
            from django.contrib.auth import get_user_model
            User = get_user_model()
            sponsor_ct = ContentType.objects.get_for_model(User)
            sponsor_obj = get_object_or_404(User, id=data['sponsor_id'])

        # TODO: Check user has permission to create Collection for this sponsor

        # Create Library (Collection)
        library = Library.objects.create(
            title=data['title'],
            summary=data.get('summary', ''),
            body=data.get('body', ''),
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=data['sponsor_id'],
            author_name=data.get('author_name', ''),
            submitted_by=request.user,
        )

        response_serializer = CollectionDetailSerializer(library)
        return Response(response_serializer.data, status=drf_status.HTTP_201_CREATED)


class CollectionDetailView(APIView):
    """
    GET /api/collections/{collection_id} - Get Collection detail
    PATCH /api/collections/{collection_id} - Update Collection metadata
    DELETE /api/collections/{collection_id} - Delete Collection

    Get, update, or delete Collection detail (Library in Collection role).
    Includes narrative metadata, counts, and ingestion status.
    Does NOT include items (use separate endpoint).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        """Get Collection detail"""
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has read access

        serializer = CollectionDetailSerializer(library)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def patch(self, request, collection_id):
        """
        Update Collection metadata.

        Body (all optional):
        {
          "title": "New Title",
          "summary": "Updated summary",
          "body": "Updated long-form description",
          "author_name": "Author Name"
        }
        """
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has write access

        serializer = CollectionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Update fields if provided
        if 'title' in data:
            library.title = data['title']
        if 'summary' in data:
            library.summary = data['summary']
        if 'body' in data:
            library.body = data['body']
        if 'author_name' in data:
            library.author_name = data['author_name']

        library.save()

        response_serializer = CollectionDetailSerializer(library)
        return Response(response_serializer.data, status=drf_status.HTTP_200_OK)

    def delete(self, request, collection_id):
        """
        Delete a Collection.

        This removes the Library and all its LibraryItems (editorial overlays).
        The underlying SourceFiles and WritingPieces are NOT deleted.
        """
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has delete access

        library.delete()

        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class CollectionAvailableFilesView(APIView):
    """
    GET /api/collections/{collection_id}/available-files/

    List all SourceFiles in this Collection's Library.
    Shows which files are already added as LibraryItems and how many times.
    Essential for "add files from existing Collections/Libraries" workflow.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        """List available SourceFiles with usage info"""
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has read access

        # Get all SourceFiles in this Library
        source_files = library.source_files.all().order_by('-created_at')

        # For each SourceFile, count how many LibraryItems reference it
        from django.contrib.contenttypes.models import ContentType
        source_file_ct = ContentType.objects.get_for_model(SourceFile)
        files_data = []
        for sf in source_files:
            item_count = library.items.filter(
                content_type=source_file_ct,
                content_object_id=sf.id
            ).count()
            files_data.append({
                'id': sf.id,
                'filename': sf.filename,
                'content_type': sf.content_type,
                'size_bytes': sf.size_bytes,
                'origin': sf.origin,
                'created_at': sf.created_at,
                'in_collection': item_count > 0,
                'item_count': item_count,
            })

        serializer = SourceFileMinimalSerializer(files_data, many=True)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class CollectionAvailableDocumentsView(APIView):
    """
    GET /api/collections/{collection_id}/available-documents/

    List all published WritingPieces available for adding to Collection.
    Shows which documents are already added as LibraryItems and how many times.
    Filters by sponsor match (same sponsor as Collection's Library).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        """List available WritingPieces with usage info"""
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has read access

        # Get all published WritingPieces with matching sponsor
        from writing.models import WritingPiece
        from django.contrib.contenttypes.models import ContentType

        writing_pieces = WritingPiece.objects.filter(
            status='published',
            sponsor_content_type=library.sponsor_content_type,
            sponsor_object_id=library.sponsor_object_id,
        ).order_by('-published_at')

        # Get ContentType for WritingPiece
        writing_piece_ct = ContentType.objects.get_for_model(WritingPiece)

        # For each WritingPiece, count how many LibraryItems reference it
        docs_data = []
        for wp in writing_pieces:
            item_count = library.items.filter(
                content_type=writing_piece_ct,
                content_object_id=wp.id
            ).count()
            docs_data.append({
                'id': wp.id,
                'title': wp.title,
                'slug': wp.slug,
                'summary': wp.summary,
                'writing_kind': wp.writing_kind,
                'status': wp.status,
                'author_name': wp.author_name,
                'published_at': wp.published_at,
                'created_at': wp.created_at,
                'in_collection': item_count > 0,
                'item_count': item_count,
            })

        serializer = WritingPieceMinimalSerializer(docs_data, many=True)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class CollectionItemListView(APIView):
    """
    GET /api/collections/{collection_id}/items
    POST /api/collections/{collection_id}/items

    List or create LibraryItems (editorial overlays).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        """
        List all items in this Collection.

        Query params:
        - folder: filter by folder_path
        - featured: filter by is_featured (true/false)
        - hidden: include hidden items (default: false)
        """
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has read access

        items = library.items.select_related('content_type').all()

        # Apply filters
        folder = request.query_params.get('folder')
        if folder:
            items = items.filter(folder_path=folder)

        featured = request.query_params.get('featured')
        if featured == 'true':
            items = items.filter(is_featured=True)

        include_hidden = request.query_params.get('hidden') == 'true'
        if not include_hidden:
            items = items.filter(is_hidden=False)

        serializer = LibraryItemSerializer(items, many=True)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def post(self, request, collection_id):
        """
        Add content to this Collection as a LibraryItem.

        Body:
        {
          "content_type": "source_file" | "writing_piece",
          "content_id": "uuid",
          "order_index": 10,  // optional
          "folder_path": "research/papers",  // optional
          "tags": ["important", "review"],  // optional
          "notes": "Key source for chapter 3",  // optional
          "is_featured": false  // optional
        }
        """
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has write access

        serializer = LibraryItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Resolve content object based on content_type
        from django.contrib.contenttypes.models import ContentType

        if data['content_type'] == 'source_file':
            # Verify SourceFile exists and belongs to this Library
            content_obj = get_object_or_404(SourceFile, id=data['content_id'])
            if content_obj.library != library:
                return Response(
                    {"detail": "SourceFile does not belong to this Collection's Library"},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )
            content_model = SourceFile

        elif data['content_type'] == 'writing_piece':
            # Verify WritingPiece exists and is published
            from writing.models import WritingPiece
            content_obj = get_object_or_404(WritingPiece, id=data['content_id'])

            if content_obj.status != 'published':
                return Response(
                    {"detail": "Only published WritingPieces can be added to Collections"},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

            # Verify sponsor matches (user has access)
            if (content_obj.sponsor_content_type != library.sponsor_content_type or
                content_obj.sponsor_object_id != library.sponsor_object_id):
                return Response(
                    {"detail": "WritingPiece sponsor must match Collection sponsor"},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

            content_model = WritingPiece

        elif data['content_type'] == 'collection':
            # Verify target Collection exists
            content_obj = get_object_or_404(Library, id=data['content_id'])

            # Prevent self-linking (will also be caught by model validation)
            if content_obj.id == library.id:
                return Response(
                    {"detail": "Collection cannot link to itself"},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

            # Verify sponsor matches (user has access)
            if (content_obj.sponsor_content_type != library.sponsor_content_type or
                content_obj.sponsor_object_id != library.sponsor_object_id):
                return Response(
                    {"detail": "Linked Collection must have same sponsor (same group/user)"},
                    status=drf_status.HTTP_400_BAD_REQUEST
                )

            content_model = Library

        else:
            return Response(
                {"detail": "Invalid content_type. Must be 'source_file', 'writing_piece', or 'collection'"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Get ContentType
        content_type = ContentType.objects.get_for_model(content_model)

        # Determine order_index if not provided
        if 'order_index' not in data:
            # Append to end
            max_index = library.items.aggregate(max_idx=models.Max('order_index'))['max_idx']
            data['order_index'] = (max_index or 0) + 1

        # Check for duplicate position
        existing = library.items.filter(
            content_type=content_type,
            content_object_id=data['content_id'],
            order_index=data['order_index']
        ).first()

        if existing:
            return Response(
                {
                    "detail": "This content already exists at this position",
                    "item_id": str(existing.id),
                },
                status=drf_status.HTTP_409_CONFLICT
            )

        # Determine title from content object if not provided
        title = data.get('title', '')
        if not title and hasattr(content_obj, 'filename'):
            # For SourceFiles, use filename as title
            title = content_obj.filename
        elif not title and hasattr(content_obj, 'title'):
            # For WritingPieces and Libraries, use their title
            title = content_obj.title

        # Create LibraryItem
        item = LibraryItem.objects.create(
            library=library,
            title=title,
            content_type=content_type,
            content_object_id=data['content_id'],
            order_index=data['order_index'],
            folder_path=data.get('folder_path', ''),
            tags=data.get('tags', []),
            notes=data.get('notes', ''),
            is_featured=data.get('is_featured', False),
        )

        response_serializer = LibraryItemSerializer(item)
        return Response(response_serializer.data, status=drf_status.HTTP_201_CREATED)


class CollectionItemDetailView(APIView):
    """
    GET /api/collections/{collection_id}/items/{item_id}
    PATCH /api/collections/{collection_id}/items/{item_id}
    DELETE /api/collections/{collection_id}/items/{item_id}

    Retrieve, update, or remove a LibraryItem.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id, item_id):
        """Get single LibraryItem"""
        library = get_object_or_404(Library, id=collection_id)
        item = get_object_or_404(LibraryItem, id=item_id, library=library)

        # TODO: Check user has read access

        serializer = LibraryItemSerializer(item)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def patch(self, request, collection_id, item_id):
        """
        Update LibraryItem (editorial overlay).

        Body (all optional):
        {
          "order_index": 5,
          "folder_path": "new/folder",
          "tags": ["updated", "tags"],
          "notes": "Updated notes",
          "is_featured": true,
          "is_hidden": false
        }
        """
        library = get_object_or_404(Library, id=collection_id)
        item = get_object_or_404(LibraryItem, id=item_id, library=library)

        # TODO: Check user has write access

        serializer = LibraryItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Update fields if provided
        if 'order_index' in data:
            item.order_index = data['order_index']
        if 'folder_path' in data:
            item.folder_path = data['folder_path']
        if 'tags' in data:
            item.tags = data['tags']
        if 'notes' in data:
            item.notes = data['notes']
        if 'is_featured' in data:
            item.is_featured = data['is_featured']
        if 'is_hidden' in data:
            item.is_hidden = data['is_hidden']

        item.save()

        response_serializer = LibraryItemSerializer(item)
        return Response(response_serializer.data, status=drf_status.HTTP_200_OK)

    def delete(self, request, collection_id, item_id):
        """
        Remove LibraryItem from Collection.

        DOES NOT delete the SourceFile (preserves IR truth).
        Only removes the editorial overlay.
        """
        library = get_object_or_404(Library, id=collection_id)
        item = get_object_or_404(LibraryItem, id=item_id, library=library)

        # TODO: Check user has write access

        item.delete()

        return Response(
            {"detail": "Item removed from Collection"},
            status=drf_status.HTTP_204_NO_CONTENT
        )


class CollectionItemReorderView(APIView):
    """
    POST /api/collections/{collection_id}/items/reorder

    Bulk reorder items in Collection.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id):
        """
        Bulk reorder LibraryItems.

        Body:
        {
          "items": [
            {"id": "uuid1", "order_index": 1},
            {"id": "uuid2", "order_index": 2},
            {"id": "uuid3", "order_index": 3}
          ]
        }

        Only the items specified are reordered.
        Other items remain at their current positions.
        """
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Check user has write access

        serializer = LibraryItemBulkReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items_data = serializer.validated_data['items']

        # Verify all items belong to this Collection
        item_ids = [item['id'] for item in items_data]
        items = LibraryItem.objects.filter(id__in=item_ids, library=library)

        if items.count() != len(item_ids):
            return Response(
                {"detail": "Some items do not belong to this Collection"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Update order_index and parent for each item
        with transaction.atomic():
            for item_data in items_data:
                item_id = item_data['id']
                order_index = item_data['order_index']
                parent_id = item_data.get('parent_id')  # Optional

                # Get the item to validate
                item = LibraryItem.objects.get(id=item_id, library=library)

                # Update fields
                item.order_index = order_index

                if 'parent_id' in item_data:
                    # Parent change requested
                    if parent_id is None or parent_id == 'null' or parent_id == '':
                        item.parent = None  # Move to root
                    else:
                        # Nest under a folder
                        try:
                            parent_item = LibraryItem.objects.get(id=parent_id, library=library)

                            # Validate parent is a folder
                            if not parent_item.is_folder:
                                return Response(
                                    {"detail": f"Cannot nest under non-folder item {parent_id}"},
                                    status=drf_status.HTTP_400_BAD_REQUEST
                                )

                            item.parent = parent_item
                        except LibraryItem.DoesNotExist:
                            return Response(
                                {"detail": f"Parent item {parent_id} not found"},
                                status=drf_status.HTTP_404_NOT_FOUND
                            )

                # Save with validation (clean() will check depth and other rules)
                try:
                    item.save()
                except Exception as e:
                    return Response(
                        {"detail": f"Validation error for item {item_id}: {str(e)}"},
                        status=drf_status.HTTP_400_BAD_REQUEST
                    )

        return Response(
            {"detail": f"Updated {len(items_data)} items"},
            status=drf_status.HTTP_200_OK
        )


class CollectionItemCopyFromView(APIView):
    """
    POST /api/collections/{collection_id}/items/copy-from/{source_collection_id}/

    Copy all items from a source Collection to this Collection.
    Creates independent LibraryItem records (not linked).
    Preserves folder structure and order.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id, source_collection_id):
        """
        Copy all LibraryItems from source Collection to target Collection.

        Args:
            collection_id: Target collection UUID
            source_collection_id: Source collection UUID

        Returns:
            {
                "detail": "Copied N items from 'Source Collection'",
                "copied_count": N,
                "folder_count": F,
                "file_count": X,
                "document_count": Y
            }
        """
        target_library = get_object_or_404(Library, id=collection_id)
        source_library = get_object_or_404(Library, id=source_collection_id)

        # TODO: Check user has write access to target_library
        # TODO: Check user has read access to source_library

        # Verify they're from the same sponsor (same organization/user)
        if (target_library.sponsor_content_type != source_library.sponsor_content_type or
            target_library.sponsor_object_id != source_library.sponsor_object_id):
            return Response(
                {"detail": "Cannot copy between Collections with different sponsors"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Prevent copying to self
        if target_library.id == source_library.id:
            return Response(
                {"detail": "Cannot copy Collection to itself"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Get all items from source, ordered by parent hierarchy then order_index
        source_items = LibraryItem.objects.filter(library=source_library).order_by('order_index')

        # Determine offset for order_index in target
        max_target_index = target_library.items.aggregate(max_idx=models.Max('order_index'))['max_idx']
        order_offset = (max_target_index or -1) + 1

        # Track mappings: source_item_id -> new_item_id (for preserving parent relationships)
        item_id_map = {}

        # Counters for response
        folder_count = 0
        file_count = 0
        document_count = 0
        collection_link_count = 0

        with transaction.atomic():
            # First pass: Create all items (parent relationships will be None initially for non-root)
            for source_item in source_items:
                # Determine new parent (if item has parent, map it to the new parent ID)
                new_parent = None
                if source_item.parent_id:
                    new_parent_id = item_id_map.get(str(source_item.parent_id))
                    if new_parent_id:
                        new_parent = LibraryItem.objects.get(id=new_parent_id)

                # Create new LibraryItem
                new_item = LibraryItem.objects.create(
                    library=target_library,
                    is_folder=source_item.is_folder,
                    title=source_item.title,
                    content_type=source_item.content_type,
                    content_object_id=source_item.content_object_id,
                    parent=new_parent,
                    order_index=source_item.order_index + order_offset,
                    folder_path=source_item.folder_path,
                    tags=source_item.tags.copy() if source_item.tags else [],
                    notes=source_item.notes,
                    is_featured=source_item.is_featured,
                    is_hidden=source_item.is_hidden,
                )

                # Track mapping
                item_id_map[str(source_item.id)] = str(new_item.id)

                # Update counters
                if source_item.is_folder:
                    folder_count += 1
                elif source_item.content_type and source_item.content_type.model == 'sourcefile':
                    file_count += 1
                elif source_item.content_type and source_item.content_type.model == 'writingpiece':
                    document_count += 1
                elif source_item.content_type and source_item.content_type.model == 'library':
                    collection_link_count += 1

        return Response(
            {
                "detail": f"Copied {len(item_id_map)} items from '{source_library.title}'",
                "copied_count": len(item_id_map),
                "folder_count": folder_count,
                "file_count": file_count,
                "document_count": document_count,
                "collection_link_count": collection_link_count,
            },
            status=drf_status.HTTP_200_OK
        )


class CollectionFileUploadView(APIView):
    """
    Upload files directly to a Collection.

    POST /api/collections/{collection_id}/upload

    This is the Collection-focused upload endpoint that:
    - Creates SourceFile metadata only
    - Does NOT trigger immediate ingestion
    - Ingestion happens asynchronously via background task

    This differs from Stackroom upload which immediately starts ingestion.
    Collection users care about curation, not immediate indexing.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id):
        """
        Handle lightweight file upload to Collection.
        Creates SourceFile and saves file content for deferred processing.
        """
        import hashlib
        import logging
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile

        logger = logging.getLogger(__name__)

        # Validate request
        serializer = CollectionFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data['file']

        # Verify Collection exists and user has access
        library = get_object_or_404(Library, id=collection_id)

        # TODO: Add permission check - verify user has write access to Collection

        # Compute file hash for deduplication
        file_content = uploaded_file.read()
        file_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file.seek(0)  # Reset file pointer

        # Check if file already exists in this Collection
        existing_file = SourceFile.objects.filter(
            library=library,
            hash_sha256=file_hash
        ).first()

        if existing_file:
            logger.info(f"Duplicate file detected: {uploaded_file.name} (hash: {file_hash[:16]})")
            return Response(
                {
                    "detail": "File already exists in collection",
                    "source_file_id": str(existing_file.id),
                    "filename": existing_file.filename,
                    "status": "duplicate",
                },
                status=drf_status.HTTP_409_CONFLICT
            )

        # Save file content to storage for deferred processing
        # Store in: stackroom_uploads/{library_id}/{hash}_{filename}
        storage_path = f"stackroom_uploads/{library.id}/{file_hash[:16]}_{uploaded_file.name}"
        saved_path = default_storage.save(storage_path, ContentFile(file_content))

        logger.info(f"Saved file to storage: {saved_path}")

        # Create SourceFile with path to saved file
        source_file = SourceFile.objects.create(
            library=library,
            origin="upload",
            path=saved_path,  # Path to file in storage
            filename=uploaded_file.name,
            content_type=uploaded_file.content_type or 'application/octet-stream',
            size_bytes=uploaded_file.size,
            hash_sha256=file_hash,
            created_by=request.user if request.user.is_authenticated else None,
        )

        logger.info(f"Created SourceFile {source_file.id} for Collection {collection_id}: {uploaded_file.name}")

        # NOTE: No ingestion run created here
        # Background task will pick up unprocessed files and ingest them

        # Return response
        response_data = {
            "source_file_id": str(source_file.id),
            "filename": uploaded_file.name,
            "status": "uploaded",
        }

        response_serializer = CollectionFileUploadResponseSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.validated_data, status=drf_status.HTTP_201_CREATED)


# Import models at bottom to avoid circular import issues
from django.db import models
