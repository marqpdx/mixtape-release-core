# writing/api/sponsor_views.py

"""
Generic sponsor-based views for writing content.
Works with both Group and Member sponsors.
"""

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.db import models
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingWorkingCopy
from .serializers import WritingWorkingCopySerializer
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.models import WritingPiece


# ==============================================================================
# DEPRECATED: SponsorPlacementsListView
# ==============================================================================
# WritingPlacement has been replaced by ContentPlacement in app.publishing
# This view will be reimplemented in Phase 5 using the universal publishing system
#
# Replacement will use:
# - publishing.models.ContentPlacement
# - publishing.serializers.ContentPlacementSerializer
# - content_display service for resolution
# ==============================================================================


class SponsorPlacementsListView(APIView):
    """
    List all placements for a given sponsor (group or member).

    URL pattern: /api/writing/placements?sponsor_type=group&sponsor_slug=my-group
    Query params:
      - sponsor_type: 'group' or 'member'
      - sponsor_slug: slug or username of the sponsor
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        sponsor_type = request.query_params.get("sponsor_type")
        sponsor_slug = request.query_params.get("sponsor_slug")

        if not sponsor_type or not sponsor_slug:
            return Response([], status=status.HTTP_200_OK)

        sponsor = None
        target_ct = None
        if sponsor_type == "group":
            from groups.models import Group
            sponsor = Group.objects.filter(slug=sponsor_slug).first()
            target_ct = ContentType.objects.get_for_model(Group)
        elif sponsor_type == "member":
            User = get_user_model()
            # Members don't have slugs; sponsor_slug is the username.
            sponsor = User.objects.filter(username=sponsor_slug).first()
            target_ct = ContentType.objects.get_for_model(User)
        else:
            return Response([], status=status.HTTP_200_OK)

        if not sponsor:
            return Response([], status=status.HTTP_200_OK)

        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        placements = ContentPlacement.objects.filter(
            target_content_type=target_ct,
            target_object_id=sponsor.id,
            source_content_type=ct_piece,
            channel="feed",
        ).order_by("-created_at")

        user = request.user if request.user.is_authenticated else None
        results = []

        for placement in placements:
            if not can_view_placement(placement, user):
                continue
            try:
                payload = get_display_payload(placement)
            except Exception:
                continue

            piece = payload.get("source")
            if not piece or getattr(piece, "status", None) != "published":
                continue

            metadata = payload.get("metadata") or {}
            author_name = getattr(piece, "author_name", None)
            if not author_name and getattr(piece, "author", None):
                author_name = piece.author.get_full_name() or piece.author.username

            results.append(
                {
                    "id": str(placement.id),
                    "piece_id": str(piece.id),
                    "piece_slug": piece.slug,
                    "piece_title": metadata.get("title") or piece.title,
                    "piece_body_json": metadata.get("body_json") or piece.body_json,
                    "piece_status": piece.status,
                    "published_at": piece.published_at,
                    "pinned_at": piece.pinned_at,
                    "author_name": author_name,
                    "visibility": placement.visibility,
                    "is_pinned": bool(piece.pinned_at),
                    "is_announcement": piece.writing_kind == "announcement",
                    "order": 0,
                    "created_at": placement.created_at,
                    "updated_at": placement.updated_at,
                    "display": {
                        "title": metadata.get("title"),
                        "excerpt": metadata.get("excerpt"),
                        "is_excerpt": metadata.get("is_excerpt"),
                        "body_json": metadata.get("body_json"),
                    },
                }
            )

        return Response(results, status=status.HTTP_200_OK)


class SponsorDraftsListView(generics.ListAPIView):
    """
    List all drafts (WorkingCopies) for a given sponsor.

    URL pattern: /api/writing/drafts?sponsor_type=group&sponsor_slug=my-group
    Query params:
      - sponsor_type: 'group' or 'member'
      - sponsor_slug: slug of the sponsor
    """
    serializer_class = WritingWorkingCopySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # No pagination for drafts

    def get_queryset(self):
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_slug = self.request.query_params.get("sponsor_slug")
        user = self.request.user

        if not sponsor_type or not sponsor_slug:
            return WritingWorkingCopy.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == "group":
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == "member":
                User = get_user_model()
                content_type = ContentType.objects.get_for_model(User)
                # Members don't have slugs; sponsor_slug is the username.
                sponsor = User.objects.get(username=sponsor_slug)
            else:
                return WritingWorkingCopy.objects.none()
        except Exception:
            return WritingWorkingCopy.objects.none()

        # Get filter parameter: 'my', 'shared', 'all'
        filter_type = self.request.query_params.get("filter", "my")

        # Base queryset for drafts
        base_qs = WritingWorkingCopy.objects.filter(
            piece__sponsor_content_type=content_type,
            piece__sponsor_object_id=sponsor.id,
            piece__status="draft",
        ).exclude(
            piece__is_empty=True
        ).select_related(
            "piece",
            "piece__author",
            "user",
            "user__profile",
            "dispatch_content"
        ).prefetch_related(
            "dispatch_content__collaborator_assignments__user"
        )

        if filter_type == "my":
            # Only show user's own solo drafts (exclude collaborative)
            qs = base_qs.filter(user=user, dispatch_content__isnull=True)
        elif filter_type == "shared":
            # Only show collaborative drafts the user owns or collaborates on
            from dispatch.models import DispatchContent
            qs = base_qs.filter(
                models.Q(user=user, dispatch_content__isnull=False) |  # User's collaborative drafts
                models.Q(dispatch_content__collaborators=user)  # Drafts shared with user
            ).distinct()
        elif filter_type == "all":
            # Show all drafts (owned or collaborative)
            qs = base_qs.filter(
                models.Q(user=user) |
                models.Q(dispatch_content__collaborators=user)
            ).distinct()
        else:
            # Default to 'my'
            qs = base_qs.filter(user=user)

        return qs.order_by("-last_saved_at")


class SponsorDraftDeleteView(generics.DestroyAPIView):
    """
    Delete a working copy (draft) by ID.
    Only the draft owner, the piece author, or staff can delete.
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = WritingWorkingCopy.objects.select_related("piece")
    lookup_field = "pk"

    def get_object(self):
        wc = super().get_object()
        user = self.request.user

        if wc.user_id != user.id and wc.piece.author_id != user.id and not getattr(user, "is_staff", False):
            raise PermissionDenied("You do not have permission to delete this draft.")

        return wc
