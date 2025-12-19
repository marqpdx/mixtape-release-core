# writing/api/sponsor_views.py
"""
Generic sponsor-based views for writing content.
Works with both Group and Member sponsors.
"""

from django.contrib.contenttypes.models import ContentType
from django.db import models
from rest_framework import generics, permissions

from writing.models import WritingPlacement, WritingWorkingCopy

from .serializers import WritingPlacementSerializer, WritingWorkingCopySerializer


class SponsorPlacementsListView(generics.ListAPIView):
    """
    List all placements for a given sponsor (Group or Member).

    URL pattern: /api/writing/placements?sponsor_type=group&sponsor_slug=my-group
    Query params:
      - sponsor_type: 'group' or 'member'
      - sponsor_slug: slug of the sponsor
    """
    serializer_class = WritingPlacementSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_slug = self.request.query_params.get("sponsor_slug")

        if not sponsor_type or not sponsor_slug:
            return WritingPlacement.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == "group":
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == "member":
                from users.models import User
                content_type = ContentType.objects.get_for_model(User)
                sponsor = User.objects.get(username=sponsor_slug)  # or however members are identified
            else:
                return WritingPlacement.objects.none()
        except Exception:
            return WritingPlacement.objects.none()

        # Filter placements by sponsor
        qs = WritingPlacement.objects.filter(
            piece__sponsor_content_type=content_type,
            piece__sponsor_object_id=sponsor.id
        ).select_related(
            "piece",
            "piece__author",
            "target_content_type"
        ).prefetch_related(
            "piece__versions"
        ).order_by("-piece__pinned_at", "-piece__published_at", "-updated_at")

        return qs


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
                from users.models import User
                content_type = ContentType.objects.get_for_model(User)
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
