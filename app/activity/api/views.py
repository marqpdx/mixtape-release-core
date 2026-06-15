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
from chat.models import ChatMessage, ConversationStatusTracker


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
            ConversationStatusTracker.objects
            .filter(user=user)
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


class GroupPulseView(APIView):
    """
    GET /api/activity/group-pulse
    Returns per-group activity flags for all groups the current user belongs to.
    Checks for Actions in the last 7 days.

    Response:
    {
      "<group-uuid>": {
        "livewire": true,
        "threadworks": false,
        "writing": true,
        "earthlab": false,
        "members": true
      },
      ...
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    # Map activity codes to pulse categories
    CODE_TO_CATEGORY = {
        "group.livewire.message": "livewire",
        "group.threadworks.post_created": "threadworks",
        "group.post.created": "writing",
        "group.announcement": "writing",
        "group.earthlab.course_updated": "earthlab",
        "group.member.joined": "members",
        "group.join_request.submitted": "members",
        "group.member.profile_updated": "members",
        "group.collection.item_added": "collections",
        "group.collection.updated": "collections",
        "group.almanac.event_published": "almanac",
        "group.almanac.occurrence_updated": "almanac",
        "group.circle.active": "circles",
    }

    def get(self, request):
        from datetime import timedelta
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from groups.models import Group
        from groups.models.membership import GroupMembership
        from activity.models import Action

        User = get_user_model()
        user = request.user
        user_ct = ContentType.objects.get_for_model(User)
        group_ct = ContentType.objects.get_for_model(Group)

        # Get all group IDs where user has active membership
        group_ids = list(
            GroupMembership.objects.filter(
                member_content_type=user_ct,
                member_object_id=user.id,
                is_active=True,
            ).values_list("group_id", flat=True)
        )

        if not group_ids:
            return Response({})

        # Query actions in the last 7 days for these groups
        cutoff = timezone.now() - timedelta(days=7)
        actions = (
            Action.objects.filter(
                context_content_type=group_ct,
                context_id__in=[str(gid) for gid in group_ids],
                occurs_at__gte=cutoff,
                activity_code__in=list(self.CODE_TO_CATEGORY.keys()),
            )
            .values("context_id", "activity_code")
            .distinct()
        )

        # Build pulse dict
        pulse = {}
        for row in actions:
            gid = row["context_id"]
            category = self.CODE_TO_CATEGORY.get(row["activity_code"])
            if category:
                if gid not in pulse:
                    pulse[gid] = {
                        "livewire": False,
                        "threadworks": False,
                        "writing": False,
                        "earthlab": False,
                        "members": False,
                    }
                pulse[gid][category] = True

        return Response(pulse)


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


class GroupActivityFeedView(APIView):
    """
    GET /api/activity/group-feed/<group_slug>/
    Returns the 30 most recent Actions scoped to a group.
    Requires the requesting user to be an active group member.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, group_slug):
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from groups.models import Group
        from groups.models.membership import GroupMembership
        from activity.models import Action

        User = get_user_model()

        try:
            group = Group.objects.get(slug=group_slug, is_active=True)
        except Group.DoesNotExist:
            return Response({"error": "Not found"}, status=404)

        user_ct = ContentType.objects.get_for_model(User)
        is_member = GroupMembership.objects.filter(
            group_id=group.id,
            member_content_type=user_ct,
            member_object_id=request.user.id,
            is_active=True,
        ).exists()

        if not is_member:
            return Response({"error": "Forbidden"}, status=403)

        group_ct = ContentType.objects.get_for_model(Group)
        actions = list(
            Action.objects.filter(
                context_content_type=group_ct,
                context_id=str(group.id),
            ).order_by("-occurs_at")[:30]
        )

        # Batch-resolve display names for user actors
        user_actor_ids = list({
            a.actor_id for a in actions
            if a.actor_label == "user" and a.actor_id
        })
        user_map: dict[str, str] = {}
        if user_actor_ids:
            for u in User.objects.filter(id__in=user_actor_ids).only("id", "username"):
                user_map[str(u.id)] = getattr(u, "display_name", None) or u.username

        results = []
        for action in actions:
            if action.actor_label == "user" and action.actor_id:
                actor_name = user_map.get(str(action.actor_id), "Someone")
            elif action.actor_label == "group":
                actor_name = group.title
            else:
                actor_name = "System"

            results.append({
                "id": str(action.id),
                "activity_code": action.activity_code,
                "verb": action.verb,
                "actor_name": actor_name,
                "occurs_at": action.occurs_at.isoformat(),
                "metadata": action.metadata,
            })

        return Response(results)
