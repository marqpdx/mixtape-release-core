from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from oauth2_provider.contrib.rest_framework import OAuth2Authentication

from feedback.models import FeedbackBeacon, FeedbackItem
from feedback.api.serializers import FeedbackBeaconSerializer, FeedbackItemCreateSerializer
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
@permission_classes([IsAuthenticated])
def feedback_summary(request) -> Response:
    if not request.user.is_superuser:
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    new_count = FeedbackItem.objects.filter(status=FeedbackItem.Status.NEW).count()
    total_count = FeedbackItem.objects.count()
    return Response({"data": {"new": new_count, "total": total_count}})
