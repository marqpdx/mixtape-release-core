# writing/api/storyline_views.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from fundamentals.models import Follow
from writing.models import LeafPlacement

from .serializers import LeafPlacementSerializer


User = get_user_model()


class GroupStorylineFeedView(APIView):
    """
    GET /api/storyline/groups/<uuid:group_id>
    Returns active LeafPlacements for a group storyline.
    Requires authenticated active group membership.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, group_id):
        from groups.models import Group
        group = get_object_or_404(Group, pk=group_id)

        if not group.is_member(request.user):
            raise PermissionDenied("You must be a member of this group to view its storyline.")

        ct = ContentType.objects.get_for_model(Group)
        placements = (
            LeafPlacement.objects.filter(
                target_content_type=ct,
                target_object_id=group.id,
                status="active",
            )
            .select_related(
                "leaf",
                "leaf__author",
                "leaf__author__profile",
                "placed_by",
                "placed_by__profile",
            )
            .prefetch_related("reactions")
            .order_by("-created_at")
        )

        serializer = LeafPlacementSerializer(
            placements, many=True, context={"request": request}
        )
        return Response(serializer.data)


class PersonalStorylineFeedView(APIView):
    """
    GET /api/storyline/users/<uuid:user_id>
    Returns active LeafPlacements for a user's personal storyline.
    Access rules:
    - Own storyline: always visible
    - Other user: must be following them (OQ-1 resolution: followers only)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        target_user = get_object_or_404(User, pk=user_id)
        viewer = request.user

        if viewer.id != target_user.id:
            is_following = Follow.objects.filter(
                follower=viewer, following=target_user
            ).exists()
            if not is_following:
                raise PermissionDenied(
                    "You must follow this user to view their personal storyline."
                )

        ct = ContentType.objects.get_for_model(User)
        placements = (
            LeafPlacement.objects.filter(
                target_content_type=ct,
                target_object_id=target_user.id,
                status="active",
            )
            .select_related(
                "leaf",
                "leaf__author",
                "leaf__author__profile",
                "placed_by",
                "placed_by__profile",
            )
            .prefetch_related("reactions")
            .order_by("-created_at")
        )

        serializer = LeafPlacementSerializer(
            placements, many=True, context={"request": request}
        )
        return Response(serializer.data)
