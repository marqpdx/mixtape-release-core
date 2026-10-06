# writing/api/focus_views.py
# Focus-Centered Writing ADR (puddlejump decisions/focus-centered-writing-adr/),
# Phase 2 (FCW-5): Focus model + endpoints.
#
# GET/POST /api/writing/focuses                 — list active Focuses for the
#                                                  user / create one
# GET      /api/writing/focuses/<pk>             — retrieve one (deep-link resume)
# PATCH    /api/writing/focuses/<pk>/state       — update resume state
# POST     /api/writing/focuses/<pk>/resolve     — mark resolved
#
# Superuser-gated for now (2026-10-06), matching the rest of Focus-Centered
# Writing's temporary access model (see RecentDraftsListView and the
# UnifiedNavbar "Write" entry) — widen alongside those to IsAuthenticated at
# general release, not independently.

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.api.permissions import IsSuperUser
from writing.models import Focus, Issue
from writing.api.issue_views import _can_manage_issue
from writing.api.serializers import (
    FocusCreateSerializer,
    FocusSerializer,
    FocusStateUpdateSerializer,
)


def _can_manage_target(target_content_type, target_object_id, user):
    """
    Only Issue targets exist in Phase 2. Reuses the Issue ownership check
    so a Focus can't be pointed at an Issue the requesting user has no
    rights over.
    """
    if target_content_type.model_class() is Issue:
        issue = get_object_or_404(Issue, id=target_object_id)
        return _can_manage_issue(issue, user)
    return False


def _get_owned_focus(user, focus_id):
    """
    Strictly per-user, no staff/superuser override: a Focus is personal
    attention-state ("list active Focuses for a user", ADR §6), not a
    shared or support-inspectable object like a Storyboard. This matters
    concretely during the current pre-release window, where every caller
    who can reach these endpoints at all is a superuser (IsSuperUser is a
    temporary feature gate here, not a data-access escalation) -- without
    this, any two users of the feature could read/edit each other's Focus.
    """
    focus = get_object_or_404(Focus, id=focus_id)
    if focus.user_id != user.id:
        raise PermissionDenied("You cannot access this Focus.")
    return focus


class FocusListCreateView(generics.GenericAPIView):
    permission_classes = [IsSuperUser]

    def get(self, request):
        focuses = Focus.objects.filter(
            user=request.user, status=Focus.Status.ACTIVE,
        ).select_related("target_content_type")
        return Response(FocusSerializer(focuses, many=True).data)

    def post(self, request):
        serializer = FocusCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_content_type = serializer.validated_data["target_content_type"]
        target_object_id = serializer.validated_data["target_object_id"]

        if not _can_manage_target(target_content_type, target_object_id, request.user):
            raise PermissionDenied("You cannot manage this Focus target.")

        focus = Focus.objects.create(
            user=request.user,
            verb=serializer.validated_data["verb"],
            target_content_type=target_content_type,
            target_object_id=target_object_id,
        )
        return Response(FocusSerializer(focus).data, status=status.HTTP_201_CREATED)


class FocusDetailView(APIView):
    permission_classes = [IsSuperUser]

    def get(self, request, pk):
        focus = _get_owned_focus(request.user, pk)
        return Response(FocusSerializer(focus).data)


class FocusStateUpdateView(APIView):
    permission_classes = [IsSuperUser]

    def patch(self, request, pk):
        focus = _get_owned_focus(request.user, pk)
        if focus.status != Focus.Status.ACTIVE:
            raise ValidationError("Only an active Focus can have its state updated.")
        serializer = FocusStateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        focus.state = serializer.validated_data["state"]
        focus.save(update_fields=["state", "updated_at"])
        return Response(FocusSerializer(focus).data)


class FocusResolveView(APIView):
    permission_classes = [IsSuperUser]

    def post(self, request, pk):
        focus = _get_owned_focus(request.user, pk)
        if focus.status != Focus.Status.ACTIVE:
            raise ValidationError("Only an active Focus can be resolved.")
        focus.status = Focus.Status.RESOLVED
        focus.resolved_at = timezone.now()
        focus.save(update_fields=["status", "resolved_at", "updated_at"])
        return Response(FocusSerializer(focus).data)
