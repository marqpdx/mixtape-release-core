# broadcast/api/views.py
import logging

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.mixins import RetrieveModelMixin, ListModelMixin

from broadcast.api.serializers import (
    BroadcastDeliverySerializer,
    GroupBroadcastCreateSerializer,
    GroupBroadcastSerializer,
    UserBroadcastPreferencesSerializer,
)
from broadcast.models import BroadcastDelivery, GroupBroadcast, UserBroadcastPreferences
from groups.models import Group, GroupMembership

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission helpers (mirrors the workbench pattern)
# ---------------------------------------------------------------------------

def _get_group_or_404(slug: str) -> Group:
    return get_object_or_404(Group, slug=slug)


def _require_steward(user, group: Group) -> None:
    """Raise PermissionDenied if user is not steward+ in the group."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    is_steward = GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        deleted_at__isnull=True,
        roles__overlap=["steward", "admin", "owner"],
    ).exists()
    if not is_steward:
        raise PermissionDenied("Sending broadcasts requires steward role or higher.")


def _require_member(user, group: Group) -> None:
    """Raise PermissionDenied if user is not a member of the group."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_ct = ContentType.objects.get_for_model(User)
    is_member = GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        deleted_at__isnull=True,
    ).exists()
    if not is_member:
        raise PermissionDenied("You are not a member of this group.")


# ---------------------------------------------------------------------------
# GroupBroadcast views
# ---------------------------------------------------------------------------

class GroupBroadcastListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/broadcast/groups/<slug>/broadcasts/   — list group's broadcasts (steward+)
    POST /api/broadcast/groups/<slug>/broadcasts/   — create draft broadcast (steward+)
    """
    permission_classes = [IsAuthenticated]

    def get_group(self):
        if not hasattr(self, "_group"):
            self._group = _get_group_or_404(self.kwargs["slug"])
        return self._group

    def get_serializer_class(self):
        if self.request.method == "POST":
            return GroupBroadcastCreateSerializer
        return GroupBroadcastSerializer

    def get_queryset(self):
        group = self.get_group()
        _require_steward(self.request.user, group)
        return (
            GroupBroadcast.objects
            .filter(group=group)
            .prefetch_related("audiences")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        group = self.get_group()
        _require_steward(self.request.user, group)
        broadcast = serializer.save(group=group, created_by=self.request.user)
        logger.info(
            "broadcast_created group=%s broadcast=%s by=%s",
            group.slug, broadcast.pk, self.request.user.id,
        )


class GroupBroadcastDetailView(generics.RetrieveAPIView):
    """
    GET /api/broadcast/groups/<slug>/broadcasts/<pk>/
    """
    permission_classes = [IsAuthenticated]
    serializer_class = GroupBroadcastSerializer

    def get_object(self):
        group = _get_group_or_404(self.kwargs["slug"])
        _require_steward(self.request.user, group)
        return get_object_or_404(GroupBroadcast, pk=self.kwargs["pk"], group=group)


class GroupBroadcastSendView(APIView):
    """
    POST /api/broadcast/groups/<slug>/broadcasts/<pk>/send/

    Transitions status draft → queued and fires the broadcast.
    If scheduled_at is set, the Celery beat task handles dispatch timing.
    If scheduled_at is null, dispatch fires immediately.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, slug, pk):
        group = _get_group_or_404(slug)
        _require_steward(request.user, group)

        broadcast = get_object_or_404(GroupBroadcast, pk=pk, group=group)

        if broadcast.status not in (GroupBroadcast.Status.DRAFT,):
            return Response(
                {"error": f"Cannot send a broadcast in '{broadcast.status}' status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        broadcast.status = GroupBroadcast.Status.QUEUED
        broadcast.save(update_fields=["status"])

        # Immediate dispatch if no schedule
        if not broadcast.scheduled_at:
            from broadcast.services.broadcast_service import send_broadcast
            try:
                send_broadcast(broadcast)
            except Exception as exc:
                logger.error("broadcast_send_failed broadcast=%s error=%s", broadcast.pk, exc)
                return Response({"error": "Broadcast failed to dispatch."}, status=500)

        broadcast.refresh_from_db()
        return Response(GroupBroadcastSerializer(broadcast).data)


class GroupBroadcastDeliveriesView(generics.ListAPIView):
    """
    GET /api/broadcast/groups/<slug>/broadcasts/<pk>/deliveries/
    Delivery receipts for the steward.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = BroadcastDeliverySerializer

    def get_queryset(self):
        group = _get_group_or_404(self.kwargs["slug"])
        _require_steward(self.request.user, group)
        broadcast = get_object_or_404(GroupBroadcast, pk=self.kwargs["pk"], group=group)
        return BroadcastDelivery.objects.filter(broadcast=broadcast).select_related("user")


# ---------------------------------------------------------------------------
# UserBroadcastPreferences
# ---------------------------------------------------------------------------

class UserBroadcastPreferencesView(APIView):
    """
    GET  /api/broadcast/preferences/?group=<slug>   — get preferences for a group (or global)
    PUT  /api/broadcast/preferences/?group=<slug>   — upsert preferences
    """
    permission_classes = [IsAuthenticated]

    def _get_group(self, request):
        slug = request.query_params.get("group")
        if not slug:
            return None
        group = _get_group_or_404(slug)
        _require_member(request.user, group)
        return group

    def get(self, request):
        group = self._get_group(request)
        pref = UserBroadcastPreferences.objects.filter(
            user=request.user, group=group
        ).first()
        if not pref:
            # Return defaults without persisting
            data = {
                "id": None,
                "group": group.pk if group else None,
                "allow_in_app": True,
                "allow_email": False,
                "allow_sms": False,
            }
            return Response(data)
        return Response(UserBroadcastPreferencesSerializer(pref).data)

    def put(self, request):
        group = self._get_group(request)
        pref, _ = UserBroadcastPreferences.objects.get_or_create(
            user=request.user, group=group
        )
        serializer = UserBroadcastPreferencesSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # Never allow client to set allow_sms=True (Phase 2 only)
        validated = serializer.validated_data
        validated.pop("allow_sms", None)
        for attr, value in validated.items():
            setattr(pref, attr, value)
        pref.save()
        return Response(UserBroadcastPreferencesSerializer(pref).data)
