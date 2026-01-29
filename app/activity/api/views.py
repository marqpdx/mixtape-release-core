# activity/api/views.py
import logging
from datetime import datetime

from django.db.models import Count, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import CursorPagination

from activity.api.permissions import LoggingIsAuthenticated
from activity.api.serializers import NotificationPreferenceSerializer, NotificationSerializer
from activity.models import Notification, NotificationPreference

# If your chat models live elsewhere, adjust imports:
from chat.models import ChatMessage, ConversationParticipant


class NotificationCursorPagination(CursorPagination):
    page_size = 20
    ordering = "-last_occurred_at"
    cursor_query_param = "cursor"


logger = logging.getLogger(__name__)

class NotificationListView(generics.ListAPIView):
    """
    GET /api/notifications/?bucket=activity&is_read=false&limit=20
    Lists the user's notifications with simple filters and pagination.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = NotificationCursorPagination

    def get_queryset(self):
        user = self.request.user
        qs = Notification.objects.filter(recipient=user).select_related("action")

        bucket = self.request.query_params.get("bucket")
        if bucket:
            qs = qs.filter(bucket=bucket)

        is_read = self.request.query_params.get("is_read")
        if is_read in ("true", "false"):
            qs = qs.filter(is_read=(is_read == "true"))

        # Order newest first (priority ordering can be layered on in UI)
        qs = qs.order_by("-last_occurred_at")
        return qs


class NotificationMarkReadView(APIView):
    """
    POST /api/notifications/mark-read/
    { "ids": ["uuid1", "uuid2"] }
    Marks notifications read (and seen).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list):
            return Response({"error": "ids must be a list"}, status=400)
        qs = Notification.objects.filter(recipient=request.user, id__in=ids)
        updated = qs.update(is_read=True, is_seen=True)
        return Response({"updated": updated})


class NotificationMarkAllReadView(APIView):
    """
    POST /api/notifications/mark-all-read/?bucket=activity
    Marks all user notifications in an optional bucket as read.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        bucket = request.query_params.get("bucket")
        qs = Notification.objects.filter(recipient=request.user, is_read=False)
        if bucket:
            qs = qs.filter(bucket=bucket)
        updated = qs.update(is_read=True, is_seen=True)
        return Response({"updated": updated})


class NotificationSummaryView(APIView):
    """
    GET /api/notifications/summary/
    Returns:
    {
      "messages_unread_by_conversation": { "<conv_id>": N, ... },
      "notifications_unread_count": 7,
      "mentions_unread_count": 1,
      "notifications_unread_by_bucket": { "messages": 1, "activity": 6 }
    }
    """

    permission_classes = [LoggingIsAuthenticated]

    def get(self, request):
        user = request.user

        logger.info(f"✅ NotificationSummaryView accessed by {request.user}")

        # --- Messages unread per conversation ---
        min_time = timezone.make_aware(datetime(1970, 1, 1))
        unread_counts = (
            ConversationParticipant.objects
            .filter(user=user)
            .annotate(
                unread_count=Count(
                    "conversation__messages",
                    filter=Q(
                        conversation__messages__created__gt=Coalesce("last_read_at", Value(min_time))
                    ),
                )
            )
            .values("conversation_id", "unread_count")
        )

        unread_by_conversation: dict[str, int] = {
            str(row["conversation_id"]): row["unread_count"]
            for row in unread_counts
            if row["unread_count"] > 0
        }

        # --- Notifications unread ---
        unread = Notification.objects.filter(recipient=user, is_read=False)
        total_unread = unread.count()
        mentions_unread = unread.filter(action__activity_code="chat.mention").count()
        by_bucket = {row["bucket"]: row["c"] for row in unread.values("bucket").annotate(c=Count("id"))}

        return Response({
            "messages_unread_by_conversation": unread_by_conversation,
            "notifications_unread_count": total_unread,
            "mentions_unread_count": mentions_unread,
            "notifications_unread_by_bucket": by_bucket,
        })


class NotificationPreferenceView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationPreferenceSerializer

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        bucket = serializer.validated_data.get("bucket")
        activity_code = serializer.validated_data.get("activity_code")
        level = serializer.validated_data.get("level")

        pref, _ = NotificationPreference.objects.update_or_create(
            user=self.request.user,
            bucket=bucket,
            activity_code=activity_code,
            defaults={"level": level},
        )
        serializer.instance = pref


class NotificationDismissView(APIView):
    """
    DELETE /api/activity/<uuid:notification_id>
    Deletes a notification for the current user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, notification_id):
        deleted, _ = Notification.objects.filter(
            recipient=request.user,
            id=notification_id,
        ).delete()
        if deleted == 0:
            return Response({"error": "Not found"}, status=404)
        return Response(status=204)
