from __future__ import annotations

import logging
from datetime import date

import mimetypes

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http import FileResponse, StreamingHttpResponse
from django.utils.text import get_valid_filename
from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.contrib.contenttypes.models import ContentType

from .models import CaptureStatus, MediaCapture


def _user_can_view_capture(user, capture_id: str) -> bool:
    """
    Returns True if the user may read this capture. Two paths:
      1. Author — always allowed.
      2. Group member — capture is in a non-private collection sponsored by a
         group the user belongs to (covers public / members / unlisted).
    """
    if MediaCapture.objects.filter(id=capture_id, author=user).exists():
        return True

    from curation.models import CollectionItem
    from groups.models import GroupMembership

    mc_ct = ContentType.objects.get_for_model(MediaCapture)
    user_ct = ContentType.objects.get_for_model(user.__class__)

    items = (
        CollectionItem.objects
        .filter(
            content_type=mc_ct,
            content_object_id=capture_id,
            collection__visibility__in=['public', 'members', 'unlisted'],
        )
        .select_related('collection__sponsor_content_type')
    )

    for item in items:
        col = item.collection
        if col.visibility == 'public':
            return True
        if col.sponsor_content_type.model == 'group':
            if GroupMembership.objects.filter(
                group_id=col.sponsor_object_id,
                member_content_type=user_ct,
                member_object_id=user.id,
            ).exists():
                return True

    return False

logger = logging.getLogger(__name__)


class MediaCaptureUploadView(APIView):
    """
    POST /api/media-capture/upload/

    Accepts multipart/form-data with:
      - file      (required) — the media file
      - title     (optional) — author-supplied title
      - source_type (optional, default screencast)
      - intent_tags (optional, comma-separated or repeated field)
      - visibility_scope (optional, default crossroads)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        upload: InMemoryUploadedFile | None = request.FILES.get("file")
        if not upload:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        source_type = request.data.get("source_type", "screencast")
        title = request.data.get("title", "") or f"Screencast — {date.today().isoformat()}"
        visibility_scope = request.data.get("visibility_scope", "crossroads")

        raw_tags = request.data.getlist("intent_tags") or []
        if not raw_tags and request.data.get("intent_tags"):
            raw_tags = [t.strip() for t in request.data.get("intent_tags", "").split(",") if t.strip()]

        capture = MediaCapture.objects.create(
            source_type=source_type,
            title=title,
            author=request.user,
            status=CaptureStatus.UPLOADED,
            visibility_scope=visibility_scope,
            intent_tags=raw_tags,
            has_video=True,
        )

        safe_name = get_valid_filename(upload.name or "recording")
        storage_path = f"bridge/recordings/{capture.id}/{safe_name}"
        try:
            saved_path = default_storage.save(storage_path, upload)
        except Exception as exc:
            logger.error("MediaCapture upload to Stash failed: %s", exc, exc_info=True)
            capture.status = CaptureStatus.FAILED
            capture.save(update_fields=["status", "updated_at"])
            return Response({"error": "Upload failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        capture.media_file = saved_path
        capture.save(update_fields=["media_file", "updated_at"])

        from .tasks import transcribe_capture
        transcribe_capture.apply_async(
            kwargs={"capture_id": str(capture.id)},
            queue="transcription",
        )

        return Response(
            {"capture_id": str(capture.id), "status": capture.status},
            status=status.HTTP_201_CREATED,
        )


class MediaCaptureListView(APIView):
    """
    GET /api/media-capture/

    Returns all captures authored by the current user, newest first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        captures = (
            MediaCapture.objects.filter(author=request.user)
            .select_related("transcript")
            .order_by("-created_at")
        )
        results = []
        for c in captures:
            results.append({
                "capture_id": str(c.id),
                "title": c.title,
                "status": c.status,
                "source_type": c.source_type,
                "created_at": c.created_at.isoformat(),
                "duration_seconds": c.duration_seconds,
                "has_transcript": c.transcript is not None,
                "stackroom_ingested": bool(
                    c.transcript and c.transcript.stackroom_ingested_at
                ),
            })
        return Response(results)


class MediaCaptureDetailView(APIView):
    """
    GET /api/media-capture/{capture_id}/

    Returns capture status and transcript (if ready).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, capture_id):
        if not _user_can_view_capture(request.user, capture_id):
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            capture = MediaCapture.objects.select_related("transcript").get(id=capture_id)
        except MediaCapture.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        video_url: str | None = None
        if capture.media_file:
            video_url = request.build_absolute_uri(f"/api/media-capture/{capture.id}/stream")

        data: dict = {
            "capture_id": str(capture.id),
            "title": capture.title,
            "purpose": capture.purpose,
            "status": capture.status,
            "source_type": capture.source_type,
            "created_at": capture.created_at.isoformat(),
            "video_url": video_url,
        }

        if capture.transcript:
            t = capture.transcript
            data["transcript"] = {
                "id": str(t.id),
                "raw_text": t.raw_text,
                "body_json": t.body_json,
                "model_used": t.model_used,
                "stackroom_ingested_at": (
                    t.stackroom_ingested_at.isoformat() if t.stackroom_ingested_at else None
                ),
            }

        return Response(data)

    def patch(self, request, capture_id):
        try:
            capture = MediaCapture.objects.get(id=capture_id, author=request.user)
        except MediaCapture.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        fields = []
        if "title" in request.data:
            capture.title = request.data["title"]
            fields.append("title")
        if "purpose" in request.data:
            capture.purpose = request.data["purpose"]
            fields.append("purpose")

        if fields:
            fields.append("updated_at")
            capture.save(update_fields=fields)

        return Response({"capture_id": str(capture.id), "title": capture.title, "purpose": capture.purpose})

    def delete(self, request, capture_id):
        try:
            capture = MediaCapture.objects.select_related("transcript").get(
                id=capture_id, author=request.user
            )
        except MediaCapture.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Deactivate from Stackroom IR if ingested
        if capture.transcript and capture.transcript.stackroom_ingested_at:
            try:
                from inkwell.stackroom_integration_service import deactivate_object
                deactivate_object(capture.transcript, reason="capture_deleted")
            except Exception as exc:
                logger.warning("Stackroom deactivation failed for capture %s: %s", capture_id, exc)

        # Remove file from storage
        if capture.media_file:
            try:
                default_storage.delete(capture.media_file)
            except Exception as exc:
                logger.warning("Storage delete failed for capture %s: %s", capture_id, exc)

        capture.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MediaCaptureStreamView(APIView):
    """
    GET /api/media-capture/{capture_id}/stream

    Streams the raw media file through Django, avoiding direct MinIO/S3 CORS issues.
    Only the capture's author can stream their own file.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, capture_id):
        if not _user_can_view_capture(request.user, capture_id):
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            capture = MediaCapture.objects.get(id=capture_id)
        except MediaCapture.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not capture.media_file:
            return Response({"error": "No file."}, status=status.HTTP_404_NOT_FOUND)

        try:
            f = default_storage.open(capture.media_file, "rb")
            content_type = mimetypes.guess_type(capture.media_file)[0] or "video/webm"
            response = FileResponse(f, content_type=content_type)
            response["Content-Disposition"] = f'inline; filename="{capture.media_file.split("/")[-1]}"'
            return response
        except Exception as exc:
            logger.error("MediaCapture stream failed for %s: %s", capture_id, exc)
            return Response({"error": "Stream failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
