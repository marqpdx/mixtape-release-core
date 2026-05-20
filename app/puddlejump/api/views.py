import logging
import os

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inkwell.stackroom_http_client import ingest_text

from groups.models import Group
from groups.services.permissions import PermissionService
from ..models import Library, LibraryItem
from .serializers import PersonalPuddlejumpSerializer

logger = logging.getLogger(__name__)


class PersonalPuddlejumpView(APIView):
    """GET /api/puddlejump/personal — member's own Puddlejump library."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        library, _ = Library.objects.get_or_create(
            owner_content_type=user_ct,
            owner_object_id=user.id,
            defaults={'title': f"{user.get_full_name() or user.username}'s Library"},
        )
        serializer = PersonalPuddlejumpSerializer(library)
        return Response(serializer.data)


class GroupPuddlejumpView(APIView):
    """GET /api/puddlejump/<groupSlug>/ — group's Puddlejump manifest."""
    permission_classes = [IsAuthenticated]

    def get(self, request, group_slug):
        group = get_object_or_404(Group, slug=group_slug)

        if not PermissionService.can_user_perform_action(request.user, 'manage_puddlejump', group_slug):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        group_ct = ContentType.objects.get_for_model(group)
        library, _ = Library.objects.get_or_create(
            owner_content_type=group_ct,
            owner_object_id=group.id,
            defaults={'title': f"{group.title} Library", 'slug': f"{group_slug}-library"},
        )
        serializer = PersonalPuddlejumpSerializer(library)
        return Response(serializer.data)


# --- Sync Protocol Endpoints ---

class SyncStatusView(APIView):
    """GET /api/puddlejump/sync/status — current sync state for the member's library."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        try:
            library = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
        except Library.DoesNotExist:
            return Response({
                'library_id': None,
                'synced': False,
                'file_count': 0,
                'last_synced_at': None,
                'files': [],
            })

        files = [
            {
                'id': str(item.id),
                'source_file_id': str(item.source_file_id) if item.source_file_id else '',
                'path': item.folder_path,
                'hash': item.hash_sha256 or None,
                'size_bytes': item.size_bytes,
                'modified_at': item.updated_at.isoformat(),
            }
            for item in library.items.filter(is_folder=False)
        ]

        return Response({
            'library_id': str(library.id),
            'synced': library.last_synced_at is not None,
            'file_count': library.file_count,
            'last_synced_at': library.last_synced_at,
            'files': files,
        })


class SyncUploadView(APIView):
    """POST /api/puddlejump/sync/upload — store a file in S3 and ingest it into Stackroom IR."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        if 'file' not in request.FILES:
            return Response({'detail': 'No file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        library, _ = Library.objects.get_or_create(
            owner_content_type=user_ct,
            owner_object_id=user.id,
            defaults={'title': f"{user.get_full_name() or user.username}'s Library"},
        )

        uploaded = request.FILES['file']
        path = request.data.get('path', uploaded.name)
        client_hash = request.data.get('hash', '')

        file_bytes = uploaded.read()
        try:
            text = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return Response({'detail': 'File must be UTF-8 text.'}, status=status.HTTP_400_BAD_REQUEST)

        filename = os.path.basename(path)
        s3_key = f"puddlejump/{library.id}/{path}"
        default_storage.save(s3_key, ContentFile(file_bytes))

        source_file_id = None
        try:
            ingest_result = ingest_text(
                library_id=library.id,
                source_path=path,
                filename=filename,
                text=text,
            )
            source_file_id = ingest_result.get('source_file_id')
        except Exception:
            logger.exception("ingest_text failed for path=%s", path)

        item, _ = LibraryItem.objects.update_or_create(
            library=library,
            folder_path=path,
            defaults={
                'filename': filename,
                'size_bytes': len(file_bytes),
                'hash_sha256': client_hash,
                's3_key': s3_key,
                'source_file_id': source_file_id,
            },
        )

        return Response({
            'id': str(item.id),
            'path': path,
            'hash': item.hash_sha256,
            'size_bytes': item.size_bytes,
            'created': item.created_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class SyncDownloadView(APIView):
    """GET /api/puddlejump/sync/download/<id>/ — serve raw file bytes from S3."""
    permission_classes = [IsAuthenticated]

    def get(self, request, item_id):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        item = get_object_or_404(
            LibraryItem,
            id=item_id,
            library__owner_content_type=user_ct,
            library__owner_object_id=user.id,
        )
        if not item.s3_key:
            raise Http404
        try:
            f = default_storage.open(item.s3_key)
            content = f.read()
            f.close()
        except Exception:
            logger.exception("S3 download failed for s3_key=%s", item.s3_key)
            raise Http404
        return HttpResponse(content, content_type='text/markdown')


class SyncDeleteView(APIView):
    """DELETE /api/puddlejump/sync/delete/<id>/ — remove an item from the library."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, item_id):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        item = get_object_or_404(
            LibraryItem,
            id=item_id,
            library__owner_content_type=user_ct,
            library__owner_object_id=user.id,
        )
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SyncCompleteView(APIView):
    """POST /api/puddlejump/sync/complete — mark sync session complete, update last_synced_at."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        library, _ = Library.objects.get_or_create(
            owner_content_type=user_ct,
            owner_object_id=user.id,
            defaults={'title': f"{user.get_full_name() or user.username}'s Library"},
        )
        library.last_synced_at = timezone.now()
        library.save(update_fields=['last_synced_at', 'updated_at'])
        return Response({'last_synced_at': library.last_synced_at})
