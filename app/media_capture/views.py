from __future__ import annotations

import logging
from datetime import date

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils.text import get_valid_filename
from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CaptureStatus, MediaCapture

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
        try:
            capture = MediaCapture.objects.select_related("transcript").get(
                id=capture_id,
                author=request.user,
            )
        except MediaCapture.DoesNotExist:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        video_url: str | None = None
        if capture.media_file:
            try:
                from urllib.parse import urlparse
                raw_url = default_storage.url(capture.media_file)
                video_url = raw_url if urlparse(raw_url).scheme else request.build_absolute_uri(raw_url)
            except Exception:
                pass

        data: dict = {
            "capture_id": str(capture.id),
            "title": capture.title,
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
