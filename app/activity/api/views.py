# activity/api/views.py
import logging
from typing import Dict
from django.db.models import Count, Max, Q
from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from activity.api.permissions import LoggingIsAuthenticated
from activity.models import Notification
from activity.api.serializers import NotificationSerializer

# If your chat models live elsewhere, adjust imports:
from chat.models import ConversationParticipant, ChatMessage

logger = logging.getLogger(__name__)

class NotificationListView(generics.ListAPIView):
    """
    GET /api/notifications/?bucket=activity&is_read=false&limit=20
    Lists the user's notifications with simple filters and pagination.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer
    pagination_class = None  # optional; add PageNumberPagination if you want

    def get_queryset(self):
        user = self.request.user
        qs = Notification.objects.filter(recipient=user).select_related("action")

        bucket = self.request.query_params.get("bucket")
        if bucket:
            qs = qs.filter(bucket=bucket)

        is_read = self.request.query_params.get("is_read")
        if is_read in ("true", "false"):
            qs = qs.filter(is_read=(is_read == "true"))

        # Order: critical first, then newest
        priority_order = {"critical": 0, "normal": 1, "low": 2}
        # We can’t sort by mapping directly in ORM; a simple ordering fallback:
        qs = qs.order_by("-last_occurred_at")
        return qs[:50]  # keep it small for the drawer by default


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
        parts = (ConversationParticipant.objects
                 .filter(user=user)
                 .values("conversation_id", "last_read_at"))

        conv_last_read: Dict[str, object] = {str(p["conversation_id"]): p["last_read_at"] for p in parts}
        conv_ids = list(conv_last_read.keys())

        unread_by_conversation: Dict[str, int] = {}
        for cid in conv_ids:
            lra = conv_last_read[cid]
            qs = ChatMessage.objects.filter(conversation_id=cid)
            if lra:
                qs = qs.filter(created__gt=lra)
            unread_by_conversation[cid] = qs.count()

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
