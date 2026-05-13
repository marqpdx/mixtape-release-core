from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.decorators import api_view, permission_classes, throttle_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from oauth2_provider.contrib.rest_framework import OAuth2Authentication

from feedback.models import FeedbackBeacon, FeedbackItem
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
    beacon = FeedbackBeacon.objects.filter(key=beacon_key).first()
    if not beacon or not _is_beacon_active(beacon):
        return Response({"error": "Beacon not active"}, status=status.HTTP_400_BAD_REQUEST)

    FeedbackItem.objects.create(
        beacon=beacon,
        kind=serializer.validated_data["kind"],
        message=serializer.validated_data["message"],
        page_url=serializer.validated_data.get("page_url", ""),
        user=request.user if request.user and request.user.is_authenticated else None,
    )

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
