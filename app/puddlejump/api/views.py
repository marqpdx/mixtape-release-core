import logging

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
            return Response({'synced': False, 'file_count': 0, 'last_synced_at': None})

        return Response({
            'synced': library.last_synced_at is not None,
            'file_count': library.file_count,
            'total_size_bytes': library.total_size_bytes,
            'last_synced_at': library.last_synced_at,
        })


class SyncUploadView(APIView):
    """POST /api/puddlejump/sync/upload — register a file in the member's library."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        library, _ = Library.objects.get_or_create(
            owner_content_type=user_ct,
            owner_object_id=user.id,
            defaults={'title': f"{user.get_full_name() or user.username}'s Library"},
        )
        data = request.data
        item = LibraryItem.objects.create(
            library=library,
            title=data.get('title', ''),
            filename=data.get('filename', ''),
            folder_path=data.get('folder_path', ''),
            size_bytes=data.get('size_bytes'),
            content_type_str=data.get('content_type', ''),
            source_file_id=data.get('source_file_id'),
            tags=data.get('tags', []),
            notes=data.get('notes', ''),
            order_index=data.get('order_index', 0),
        )
        from .serializers import LibraryItemSerializer
        return Response(LibraryItemSerializer(item).data, status=status.HTTP_201_CREATED)


class SyncDownloadView(APIView):
    """GET /api/puddlejump/sync/download/<id>/ — fetch item metadata for sync."""
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
        from .serializers import LibraryItemSerializer
        return Response(LibraryItemSerializer(item).data)


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
