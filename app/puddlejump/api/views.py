import logging
import os
import uuid

from django.conf import settings as django_settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from groups.services.permissions import PermissionService
from ..models import Library, LibraryItem, LibraryItemVersion, ManifestEvent, SnapshotConfig, LibrarySnapshot
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
            file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            return Response({'detail': 'File must be UTF-8 text.'}, status=status.HTTP_400_BAD_REQUEST)

        filename = os.path.basename(path)
        version_id = uuid.uuid4()
        seaweed_key = f"puddlejump/{library.id}/{version_id}/{filename}"
        default_storage.save(seaweed_key, ContentFile(file_bytes))

        item, _ = LibraryItem.objects.update_or_create(
            library=library,
            folder_path=path,
            defaults={
                'filename': filename,
                'size_bytes': len(file_bytes),
                'hash_sha256': client_hash,
                's3_key': seaweed_key,
            },
        )

        version = LibraryItemVersion.objects.create(
            id=version_id,
            library_item=item,
            parent_version=item.current_version,
            hash_sha256=client_hash,
            seaweed_key=seaweed_key,
            size_bytes=len(file_bytes),
            created_by=request.user,
        )
        item.current_version = version
        item.save(update_fields=['current_version', 'updated_at'])

        ManifestEvent.objects.create(
            library=library,
            event_type='upload',
            library_item=item,
            version=version,
            path=path,
            hash_sha256=client_hash,
            triggered_by=request.user,
        )

        from ..tasks import ingest_library_item, generate_snapshot
        ingest_library_item.delay(str(item.id), triggered_by_id=str(request.user.pk))

        try:
            config = library.snapshot_config
            if config.is_enabled and config.frequency == 'on_transaction':
                generate_snapshot.delay(str(library.id), triggered_by_id=str(request.user.pk))
        except SnapshotConfig.DoesNotExist:
            pass

        return Response({
            'id': str(item.id),
            'path': path,
            'hash': item.hash_sha256,
            'size_bytes': item.size_bytes,
            'version_id': str(version.id),
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
        ManifestEvent.objects.create(
            library=item.library,
            event_type='delete',
            library_item=item,
            version=item.current_version,
            path=item.folder_path,
            hash_sha256=item.hash_sha256,
            triggered_by=request.user,
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


class ManifestAtTimeView(APIView):
    """GET /api/puddlejump/manifest/?at={iso_timestamp} — reconstruct the library manifest at a point in time."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.utils.dateparse import parse_datetime
        from django.utils import timezone

        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        try:
            library = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
        except Library.DoesNotExist:
            return Response({'library_id': None, 'as_of': None, 'files': []})

        at_param = request.query_params.get('at')
        if at_param:
            as_of = parse_datetime(at_param)
            if as_of is None:
                return Response({'detail': 'Invalid `at` timestamp.'}, status=status.HTTP_400_BAD_REQUEST)
            if as_of.tzinfo is None:
                as_of = timezone.make_aware(as_of)
        else:
            as_of = timezone.now()

        events = (
            ManifestEvent.objects
            .filter(library=library, created_at__lte=as_of)
            .order_by('library_item_id', 'created_at')
            .select_related('version')
        )

        manifest = {}
        for event in events:
            item_id = str(event.library_item_id) if event.library_item_id else None
            if item_id is None:
                continue
            if event.event_type == 'delete':
                manifest.pop(item_id, None)
            else:
                manifest[item_id] = {
                    'id': item_id,
                    'path': event.path,
                    'version_id': str(event.version_id) if event.version_id else None,
                    'hash': event.hash_sha256,
                    'size_bytes': event.version.size_bytes if event.version else None,
                    'event_type': event.event_type,
                }

        return Response({
            'library_id': str(library.id),
            'as_of': as_of.isoformat(),
            'files': list(manifest.values()),
        })


class SnapshotTriggerView(APIView):
    """POST /api/puddlejump/snapshots/trigger/ — manually fire a snapshot for the member's library."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        try:
            library = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
        except Library.DoesNotExist:
            return Response({'detail': 'No library found.'}, status=status.HTTP_404_NOT_FOUND)

        from ..tasks import generate_snapshot
        generate_snapshot.delay(str(library.id))
        return Response({'queued': True, 'library_id': str(library.id)}, status=status.HTTP_202_ACCEPTED)


class SnapshotListView(APIView):
    """GET /api/puddlejump/snapshots/ — list snapshots for the member's library."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        try:
            library = Library.objects.get(owner_content_type=user_ct, owner_object_id=user.id)
        except Library.DoesNotExist:
            return Response({'snapshots': []})

        snapshots = library.snapshots.order_by('-snapshot_at')
        data = [
            {
                'id': str(s.id),
                'snapshot_at': s.snapshot_at.isoformat(),
                'file_count': s.file_count,
                'total_size_bytes': s.total_size_bytes,
                'delivered_to': s.delivered_to,
                'status': s.status,
            }
            for s in snapshots
        ]
        return Response({'library_id': str(library.id), 'snapshots': data})


class SnapshotDetailView(APIView):
    """GET /api/puddlejump/snapshots/<id>/ — retrieve manifest JSON for a specific snapshot."""
    permission_classes = [IsAuthenticated]

    def get(self, request, snapshot_id):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        snapshot = get_object_or_404(
            LibrarySnapshot,
            id=snapshot_id,
            library__owner_content_type=user_ct,
            library__owner_object_id=user.id,
        )
        return Response({
            'id': str(snapshot.id),
            'library_id': str(snapshot.library_id),
            'snapshot_at': snapshot.snapshot_at.isoformat(),
            'file_count': snapshot.file_count,
            'total_size_bytes': snapshot.total_size_bytes,
            'delivered_to': snapshot.delivered_to,
            'status': snapshot.status,
            'manifest': snapshot.manifest_json,
        })


class SyncVersionListView(APIView):
    """GET /api/puddlejump/sync/versions/<item_id>/ — list all versions for a library item."""
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
        versions = item.versions.select_related('created_by').order_by('-created_at')
        data = [
            {
                'id': str(v.id),
                'hash_sha256': v.hash_sha256,
                'size_bytes': v.size_bytes,
                'created_at': v.created_at.isoformat(),
                'created_by': v.created_by.get_full_name() if v.created_by else None,
                'is_current': item.current_version_id == v.id,
            }
            for v in versions
        ]
        return Response({'item_id': str(item.id), 'versions': data})


class SyncRestoreView(APIView):
    """POST /api/puddlejump/sync/restore/<item_id>/ — serve bytes for a specific version."""
    permission_classes = [IsAuthenticated]

    def post(self, request, item_id):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user)
        item = get_object_or_404(
            LibraryItem,
            id=item_id,
            library__owner_content_type=user_ct,
            library__owner_object_id=user.id,
        )
        version_id = request.data.get('version_id')
        if not version_id:
            return Response({'detail': 'version_id required.'}, status=status.HTTP_400_BAD_REQUEST)

        version = get_object_or_404(LibraryItemVersion, id=version_id, library_item=item)

        try:
            f = default_storage.open(version.seaweed_key)
            content = f.read()
            f.close()
        except Exception:
            logger.exception("Restore download failed for seaweed_key=%s", version.seaweed_key)
            raise Http404

        return HttpResponse(content, content_type='text/markdown')


# ── Switchboard-mediated retrieve / find ──────────────────────────────────────

_DEFAULT_TENANT_ID = getattr(django_settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(django_settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")


def _get_user_library(request):
    """Return the personal Library for the requesting user, or None."""
    user_ct = ContentType.objects.get_for_model(request.user)
    return Library.objects.filter(
        owner_content_type=user_ct,
        owner_object_id=request.user.id,
    ).first()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def retrieve_async_proxy(request):
    from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus
    from mixtape.celery_app import app as celery_app

    query = (request.data.get("query") or "").strip()
    library_id_raw = (request.data.get("library_id") or "").strip() or None
    limit = min(int(request.data.get("limit") or 10), 50)
    score_threshold_raw = request.data.get("score_threshold")
    score_threshold = float(score_threshold_raw) if score_threshold_raw is not None else None

    if not query:
        return JsonResponse({"detail": "query is required."}, status=400)

    if library_id_raw:
        try:
            library_id = str(uuid.UUID(library_id_raw))
        except ValueError:
            return JsonResponse({"detail": "library_id must be a valid UUID."}, status=400)
    else:
        library = _get_user_library(request)
        if not library:
            return JsonResponse({"detail": "No library found for this user."}, status=404)
        library_id = str(library.id)

    tenant_id = str(_DEFAULT_TENANT_ID)
    tenant_namespace = str(_DEFAULT_TENANT_NAMESPACE)

    action_run = ActionRun.objects.create(
        tool_name="puddlejump.retrieve",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "query_length": len(query),
            "library_id": library_id,
            "limit": limit,
            "score_threshold": score_threshold,
        },
    )

    retrieve_payload = {
        "query": query,
        "library_id": library_id,
        "limit": limit,
        "score_threshold": score_threshold,
    }

    celery_app.send_task(
        "switchboard.retrieve_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": retrieve_payload,
            "retrieve_payload": retrieve_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued retrieve action_run=%s user=%s library=%s query_len=%s",
        action_run.id, request.user.pk, library_id, len(query),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def find_async_proxy(request):
    from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus
    from mixtape.celery_app import app as celery_app

    query = (request.data.get("query") or "").strip()
    library_id_raw = (request.data.get("library_id") or "").strip() or None
    limit = min(int(request.data.get("limit") or 10), 50)
    score_threshold_raw = request.data.get("score_threshold")
    score_threshold = float(score_threshold_raw) if score_threshold_raw is not None else None
    source_file_ids_raw = request.data.get("source_file_ids") or []

    if not query:
        return JsonResponse({"detail": "query is required."}, status=400)

    if library_id_raw:
        try:
            library_id = str(uuid.UUID(library_id_raw))
        except ValueError:
            return JsonResponse({"detail": "library_id must be a valid UUID."}, status=400)
    else:
        library = _get_user_library(request)
        if not library:
            return JsonResponse({"detail": "No library found for this user."}, status=404)
        library_id = str(library.id)

    source_file_ids = []
    for fid in source_file_ids_raw:
        try:
            source_file_ids.append(str(uuid.UUID(str(fid))))
        except ValueError:
            return JsonResponse({"detail": f"Invalid UUID in source_file_ids: {fid}"}, status=400)

    tenant_id = str(_DEFAULT_TENANT_ID)
    tenant_namespace = str(_DEFAULT_TENANT_NAMESPACE)

    action_run = ActionRun.objects.create(
        tool_name="puddlejump.find",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=tenant_id,
        tenant_namespace=tenant_namespace,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(request.user.pk),
        request_payload={
            "query_length": len(query),
            "library_id": library_id,
            "limit": limit,
            "score_threshold": score_threshold,
            "source_file_count": len(source_file_ids),
        },
    )

    retrieve_payload = {
        "query": query,
        "library_id": library_id,
        "limit": limit,
        "score_threshold": score_threshold,
        "source_file_ids": source_file_ids or None,
    }

    celery_app.send_task(
        "switchboard.retrieve_async",
        kwargs={
            "action_run_id": str(action_run.id),
            "tenant_id": tenant_id,
            "tenant_namespace": tenant_namespace,
            "principal_user_id": str(request.user.pk),
            "principal_service_token_id": None,
            "request_payload": retrieve_payload,
            "retrieve_payload": retrieve_payload,
        },
        queue="switchboard",
    )

    logger.info(
        "Enqueued find action_run=%s user=%s library=%s source_files=%d query_len=%s",
        action_run.id, request.user.pk, library_id, len(source_file_ids), len(query),
    )

    return JsonResponse({"action_run_id": str(action_run.id)}, status=202)
