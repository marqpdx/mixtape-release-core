# writing/api/placement_views.py

from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import LeafComment, LeafPlacement, LeafPlacementReaction
from commons.models import Leaf

from .serializers import (
    LeafCommentSerializer,
    LeafPlacementCreateSerializer,
    LeafPlacementReactionSerializer,
    LeafPlacementSerializer,
)


def _resolve_target(target_dict):
    """
    Resolve a {'type': 'user'|'group', 'id': '<uuid>'} dict to (ContentType, object_id).
    Raises ValidationError on bad input.
    """
    target_type = target_dict.get("type")
    target_id = target_dict.get("id")
    if not target_type or not target_id:
        raise ValidationError("Each target must have 'type' and 'id'.")

    if target_type == "user":
        from django.contrib.auth import get_user_model
        User = get_user_model()
        ct = ContentType.objects.get_for_model(User)
    elif target_type == "group":
        from groups.models import Group
        ct = ContentType.objects.get_for_model(Group)
    else:
        raise ValidationError(f"Unknown target type: {target_type!r}. Use 'user' or 'group'.")

    return ct, target_id


class LeafPlacementCreateView(APIView):
    """
    POST /api/writing/placements
    Create one LeafPlacement per target.
    Body: { "leaf_id": "<uuid>", "targets": [{"type": "user"|"group", "id": "<uuid>"}] }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = LeafPlacementCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        leaf = get_object_or_404(Leaf, pk=data["leaf_id"], author=request.user)

        created = []
        for target_dict in data["targets"]:
            ct, obj_id = _resolve_target(target_dict)
            placement, _ = LeafPlacement.objects.get_or_create(
                leaf=leaf,
                placed_by=request.user,
                target_content_type=ct,
                target_object_id=obj_id,
                defaults={"status": "active"},
            )
            # If it was previously rescinded, reactivate it
            if placement.status == "rescinded":
                placement.status = "active"
                placement.rescinded_at = None
                placement.save(update_fields=["status", "rescinded_at", "updated_at"])
            created.append(placement)

        return Response(
            LeafPlacementSerializer(created, many=True, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class LeafPlacementDetailView(APIView):
    """
    PATCH /api/writing/placements/<uuid:pk>
    Rescind a placement.  Only the author (placed_by) or a group admin can rescind.
    Body: { "status": "rescinded" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, pk):
        placement = get_object_or_404(LeafPlacement, pk=pk)
        user = request.user

        can_rescind = placement.placed_by_id == user.id
        if not can_rescind:
            # Group admin check
            ct = placement.target_content_type
            if ct.model == "group":
                from groups.models import Group
                group = Group.objects.filter(pk=placement.target_object_id).first()
                if group and group.is_member(user):
                    membership = group.memberships.filter(
                        member_object_id=user.id
                    ).first()
                    if membership and "admin" in getattr(membership, "roles", []):
                        can_rescind = True

        if not can_rescind:
            raise PermissionDenied("You do not have permission to rescind this placement.")

        new_status = request.data.get("status")
        if new_status != "rescinded":
            return Response(
                {"detail": "Only 'rescinded' status transitions are supported via PATCH."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        placement.status = "rescinded"
        placement.rescinded_at = timezone.now()
        placement.save(update_fields=["status", "rescinded_at", "updated_at"])

        return Response(
            LeafPlacementSerializer(placement, context={"request": request}).data
        )


class PlacementCommentListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/writing/placements/<uuid:placement_id>/comments
    POST /api/writing/placements/<uuid:placement_id>/comments
    """
    serializer_class = LeafCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        placement_id = self.kwargs["placement_id"]
        return LeafComment.objects.filter(
            placement_id=placement_id,
            parent__isnull=True,
            is_approved=True,
            deleted_at__isnull=True,
        ).select_related(
            "author", "author__profile",
        ).prefetch_related(
            "replies__author", "replies__author__profile",
        )

    def perform_create(self, serializer):
        placement_id = self.kwargs["placement_id"]
        placement = get_object_or_404(LeafPlacement, pk=placement_id, status="active")
        serializer.save(author=self.request.user, placement=placement)


class PlacementCommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    PUT/DELETE /api/writing/placement-comments/<uuid:pk>
    """
    serializer_class = LeafCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return LeafComment.objects.filter(deleted_at__isnull=True)

    def get_object(self):
        obj = super().get_object()
        if obj.author_id != self.request.user.id and not self.request.user.is_staff:
            raise PermissionDenied("You do not have permission to modify this comment.")
        return obj


class PlacementReactionView(APIView):
    """
    POST /api/writing/placements/<uuid:placement_id>/reactions
    Toggle a reaction on a placement. If reaction exists, removes it (toggle).
    Body: { "reaction_name": "heart" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, placement_id):
        placement = get_object_or_404(LeafPlacement, pk=placement_id, status="active")
        reaction_name = request.data.get("reaction_name", "").strip()
        if not reaction_name:
            return Response(
                {"detail": "reaction_name is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reaction, created = LeafPlacementReaction.objects.get_or_create(
            placement=placement,
            user=request.user,
            reaction_name=reaction_name,
        )
        if not created:
            # Toggle off
            reaction.delete()
            return Response({"toggled": "off", "reaction_name": reaction_name})

        return Response(
            LeafPlacementReactionSerializer(reaction).data,
            status=status.HTTP_201_CREATED,
        )
