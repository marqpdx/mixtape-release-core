# writing/api/sponsor_views.py
"""
Generic sponsor-based views for writing content.
Works with both Group and Member sponsors.
"""

from django.contrib.contenttypes.models import ContentType
from rest_framework import generics, permissions, status
from rest_framework.response import Response

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
        sponsor_type = self.request.query_params.get('sponsor_type')
        sponsor_slug = self.request.query_params.get('sponsor_slug')

        if not sponsor_type or not sponsor_slug:
            return WritingPlacement.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == 'group':
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == 'member':
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
            'piece',
            'piece__author',
            'target_content_type'
        ).prefetch_related(
            'piece__versions'
        ).order_by('-piece__pinned_at', '-piece__published_at', '-updated_at')

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
        sponsor_type = self.request.query_params.get('sponsor_type')
        sponsor_slug = self.request.query_params.get('sponsor_slug')
        user = self.request.user

        if not sponsor_type or not sponsor_slug:
            return WritingWorkingCopy.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == 'group':
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == 'member':
                from users.models import User
                content_type = ContentType.objects.get_for_model(User)
                sponsor = User.objects.get(username=sponsor_slug)
            else:
                return WritingWorkingCopy.objects.none()
        except Exception:
            return WritingWorkingCopy.objects.none()

        # Filter drafts by sponsor and current user
        # Only show drafts for pieces the user is working on
        qs = WritingWorkingCopy.objects.filter(
            piece__sponsor_content_type=content_type,
            piece__sponsor_object_id=sponsor.id,
            piece__status='draft',
            user=user  # Only show user's own drafts
        ).exclude(
            piece__is_empty=True  # ← Add this: Filter out empty pieces
        ).select_related(
            'piece',
            'piece__author',
            'user',
            'user__profile'
        ).order_by('-last_saved_at')

        return qs
