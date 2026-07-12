from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.decorators import api_view, permission_classes, throttle_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from oauth2_provider.contrib.rest_framework import OAuth2Authentication

from feedback.models import FeedbackBeacon, FeedbackItem, FeedbackAttachment
from feedback.api.serializers import (
    FeedbackBeaconSerializer,
    FeedbackItemCreateSerializer,
    FeedbackItemListSerializer,
)
from feedback.api.throttles import FeedbackIPThrottle


def _is_beacon_active(beacon: FeedbackBeacon) -> bool:
    if not beacon.is_active:
        return False
    now = timezone.now()
    if beacon.start_at and now < beacon.start_at:
        return False
    if beacon.end_at and now > beacon.end_at:
        return False
    return True


class FeedbackItemsPermission(BasePermission):
    """
    Allow public feedback submission while keeping the feedback queue private.
    """

    def has_permission(self, request, view) -> bool:
        if request.method == "POST":
            return True
        return bool(request.user and request.user.is_authenticated)


def _create_feedback_item(request) -> Response:
    serializer = FeedbackItemCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    beacon_key = serializer.validated_data.get("beacon_key")
    beacon, _ = FeedbackBeacon.objects.get_or_create(
        key=beacon_key,
        defaults={
            "title": beacon_key.replace("_", " ").title(),
            "body_markdown": "",
            "scope": FeedbackBeacon.Scope.COMPONENT,
            "is_active": True,
        },
    )

    voice_file_id = serializer.validated_data.get("voice_file_id")
    media_capture_id = serializer.validated_data.get("media_capture_id")
    attachment_ids = serializer.validated_data.get("attachment_ids") or []

    voice_file = None
    if voice_file_id:
        from files.models import StoredFile
        voice_file = StoredFile.objects.filter(id=voice_file_id).first()

    media_capture = None
    if media_capture_id:
        from media_capture.models import MediaCapture
        media_capture = MediaCapture.objects.filter(id=media_capture_id).first()

    item = FeedbackItem.objects.create(
        beacon=beacon,
        kind=serializer.validated_data["kind"],
        message=serializer.validated_data["message"],
        page_url=serializer.validated_data.get("page_url", ""),
        work_area=serializer.validated_data.get("work_area", ""),
        voice_file=voice_file,
        voice_transcript=serializer.validated_data.get("voice_transcript", ""),
        media_capture=media_capture,
        user=request.user if request.user and request.user.is_authenticated else None,
    )

    if attachment_ids:
        from files.models import StoredFile
        files_qs = StoredFile.objects.filter(id__in=attachment_ids)
        FeedbackAttachment.objects.bulk_create([
            FeedbackAttachment(feedback_item=item, stored_file=f) for f in files_qs
        ])

    return Response({"message": "Feedback received"}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
def get_beacon(request, key: str) -> Response:
    beacon = FeedbackBeacon.objects.filter(key=key).first()
    if not beacon or not _is_beacon_active(beacon):
        return Response({"error": "Beacon not active"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"data": FeedbackBeaconSerializer(beacon).data})


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
@throttle_classes([FeedbackIPThrottle])
def create_feedback_item(request) -> Response:
    return _create_feedback_item(request)


@api_view(["GET", "POST"])
@permission_classes([FeedbackItemsPermission])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
@throttle_classes([FeedbackIPThrottle])
def feedback_items(request) -> Response:
    if request.method == "POST":
        return _create_feedback_item(request)

    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError):
        return Response({"error": "Invalid pagination parameters"}, status=status.HTTP_400_BAD_REQUEST)

    queryset = (
        FeedbackItem.objects.select_related("beacon", "user")
        .order_by("-created_at")
    )
    kind = request.query_params.get("kind")
    status_filter = request.query_params.get("status")
    if kind:
        queryset = queryset.filter(kind=kind)
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    results = queryset[start:end]

    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": FeedbackItemListSerializer(results, many=True).data,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
def feedback_checklist(request) -> Response:
    try:
        page = max(int(request.query_params.get("page", 1)), 1)
        page_size = min(max(int(request.query_params.get("page_size", 50)), 1), 100)
    except (TypeError, ValueError):
        return Response({"error": "Invalid pagination parameters"}, status=status.HTTP_400_BAD_REQUEST)

    queryset = (
        FeedbackItem.objects.select_related("beacon", "user")
        .order_by("-created_at")
    )
    kind = request.query_params.get("kind")
    status_filter = request.query_params.get("status")
    if kind:
        queryset = queryset.filter(kind=kind)
    if status_filter:
        queryset = queryset.filter(status=status_filter)

    total = queryset.count()
    start = (page - 1) * page_size
    end = start + page_size
    results = queryset[start:end]

    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": FeedbackItemListSerializer(results, many=True).data,
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def feedback_summary(request) -> Response:
    if not request.user.is_superuser:
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    new_count = FeedbackItem.objects.filter(status=FeedbackItem.Status.NEW).count()
    total_count = FeedbackItem.objects.count()
    return Response({"data": {"new": new_count, "total": total_count}})


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
@throttle_classes([FeedbackIPThrottle])
def mindful_brilliance_contact(request) -> Response:
    """
    Pass-through contact form for the Mindful Brilliance website.
    No DB persistence — sends email to connect@crossroads.place.
    """
    import logging
    from utils.email.send_transactional_email import send_transactional_email

    logger = logging.getLogger(__name__)

    name = str(request.data.get("name", "")).strip()
    email = str(request.data.get("email", "")).strip()
    organization = str(request.data.get("organization", "")).strip()
    interest = str(request.data.get("interest", "")).strip()
    message = str(request.data.get("message", "")).strip()

    if not name:
        return Response({"error": "Name is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not email:
        return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
    if "@" not in email or "." not in email.split("@")[-1]:
        return Response({"error": "Invalid email address."}, status=status.HTTP_400_BAD_REQUEST)
    if not message:
        return Response({"error": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)

    CONTACT_EMAIL = "connect@crossroads.place"

    try:
        send_transactional_email(
            subject=f"MB contact: {name}",
            to_emails=[CONTACT_EMAIL],
            template_base="email/mb_contact",
            context={
                "name": name,
                "email": email,
                "organization": organization,
                "interest": interest,
                "message": message,
            },
            reply_to=email,
        )
    except Exception as e:
        logger.error("mb_contact email failed: %s", e)
        return Response(
            {"error": "Failed to send message. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return Response({"message": "Message received."}, status=status.HTTP_200_OK)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
def update_feedback_item(request, item_id: str) -> Response:
    if not request.user.is_superuser:
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    item = FeedbackItem.objects.filter(id=item_id).first()
    if not item:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    next_status = request.data.get("status")
    next_message = request.data.get("message")
    if next_status is None and next_message is None:
        return Response({"error": "No changes supplied"}, status=status.HTTP_400_BAD_REQUEST)

    update_fields: list[str] = []
    if next_status is not None:
        allowed_statuses = {choice for choice, _ in FeedbackItem.Status.choices}
        if next_status not in allowed_statuses:
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)
        item.status = next_status
        update_fields.append("status")

    if next_message is not None:
        normalized = str(next_message).strip()
        if not normalized:
            return Response({"error": "Message cannot be empty"}, status=status.HTTP_400_BAD_REQUEST)
        item.message = normalized
        update_fields.append("message")

    item.save(update_fields=update_fields)
    return Response({"data": FeedbackItemListSerializer(item).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
@throttle_classes([FeedbackIPThrottle])
def upload_feedback_voice(request) -> Response:
    """
    POST /api/feedback/upload-voice
    Accepts multipart audio, saves as StoredFile, queues transcription.
    Returns voice_upload_id for polling / WS resolution.
    """
    import mimetypes
    from django.core.files.storage import default_storage
    from django.utils.text import get_valid_filename
    from files.models import StoredFile
    from feedback.tasks import transcribe_feedback_voice_task

    upload = request.FILES.get("file")
    if not upload:
        return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

    safe_name = get_valid_filename(upload.name or "voice_feedback.webm")
    storage_path = f"feedback/voice/{request.user.id}/{safe_name}"
    try:
        saved_path = default_storage.save(storage_path, upload)
    except Exception as exc:
        return Response({"error": "Upload failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    mime = upload.content_type or mimetypes.guess_type(safe_name)[0] or "audio/webm"
    stored_file = StoredFile.objects.create(
        file_path=saved_path,
        file_name=safe_name,
        file_type=mime,
        file_size=upload.size or 0,
        uploaded_by=request.user,
        source="feedback_voice",
    )

    transcribe_feedback_voice_task.apply_async(
        kwargs={
            "stored_file_id": str(stored_file.id),
            "username": request.user.username,
        },
        queue="transcription",
    )

    return Response(
        {"voice_upload_id": str(stored_file.id), "status": "processing"},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
@throttle_classes([FeedbackIPThrottle])
def upload_feedback_attachment(request) -> Response:
    """
    POST /api/feedback/upload-attachment
    Accepts an image file, saves as StoredFile, returns attachment_id.
    """
    import mimetypes
    from django.core.files.storage import default_storage
    from django.utils.text import get_valid_filename
    from files.models import StoredFile

    upload = request.FILES.get("file")
    if not upload:
        return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

    allowed_prefixes = ("image/",)
    mime = upload.content_type or ""
    if not any(mime.startswith(p) for p in allowed_prefixes):
        return Response({"error": "Only image files are accepted."}, status=status.HTTP_400_BAD_REQUEST)

    safe_name = get_valid_filename(upload.name or "attachment")
    storage_path = f"feedback/attachments/{request.user.id}/{safe_name}"
    try:
        saved_path = default_storage.save(storage_path, upload)
    except Exception:
        return Response({"error": "Upload failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    stored_file = StoredFile.objects.create(
        file_path=saved_path,
        file_name=safe_name,
        file_type=mime,
        file_size=upload.size or 0,
        uploaded_by=request.user,
        source="feedback_attachment",
    )

    return Response(
        {"attachment_id": str(stored_file.id)},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@authentication_classes([OAuth2Authentication, JWTAuthentication])
def feedback_voice_status(request, voice_upload_id: str) -> Response:
    """
    GET /api/feedback/voice-status/<voice_upload_id>
    Polling fallback — returns transcript when Whisper is done.
    """
    from files.models import StoredFile
    from feedback.models import FeedbackItem as _FI

    stored_file = StoredFile.objects.filter(
        id=voice_upload_id, uploaded_by=request.user, source="feedback_voice"
    ).first()
    if not stored_file:
        return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    # Check if any linked FeedbackItem already has the transcript
    item = _FI.objects.filter(voice_file_id=voice_upload_id).exclude(voice_transcript="").first()
    if item:
        return Response({"status": "ready", "transcript": item.voice_transcript})

    # Transcript not yet propagated — still processing
    return Response({"status": "processing", "transcript": ""})
