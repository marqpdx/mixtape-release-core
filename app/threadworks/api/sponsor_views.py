# threadworks/api/sponsor_views.py
"""
Generic sponsor-based views for threadworks content.
Works with both Group and Member sponsors.
"""

from django.contrib.contenttypes.models import ContentType
from rest_framework import generics, permissions
from rest_framework.response import Response

from threadworks.models import Forum, Discussion
from .serializers import ForumSerializer, DiscussionSerializer


class SponsorForumsListView(generics.ListAPIView):
    """
    List all forums for a given sponsor (Group or Member).

    URL pattern: /api/threadworks/forums?sponsor_type=group&sponsor_slug=crossroads
    Query params:
      - sponsor_type: 'group' or 'member'
      - sponsor_slug: slug of the sponsor
    """
    serializer_class = ForumSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_slug = self.request.query_params.get("sponsor_slug")

        if not sponsor_type or not sponsor_slug:
            return Forum.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == "group":
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == "member":
                from django.contrib.auth import get_user_model
                User = get_user_model()
                content_type = ContentType.objects.get_for_model(User)
                sponsor = User.objects.get(username=sponsor_slug)
            else:
                return Forum.objects.none()
        except Exception:
            return Forum.objects.none()

        # Filter forums by sponsor
        qs = Forum.objects.filter(
            sponsor_content_type=content_type,
            sponsor_object_id=sponsor.id,
            is_archived=False
        ).select_related(
            "submitted_by",
            "sponsor_content_type"
        ).prefetch_related(
            "discussions"
        ).order_by("-updated_at")

        return qs


class SponsorDiscussionsListView(generics.ListAPIView):
    """
    List all discussions for a given sponsor's forums.

    URL pattern: /api/threadworks/discussions?sponsor_type=group&sponsor_slug=crossroads
    Query params:
      - sponsor_type: 'group' or 'member'
      - sponsor_slug: slug of the sponsor
      - forum_slug: (optional) filter to specific forum
    """
    serializer_class = DiscussionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        sponsor_type = self.request.query_params.get("sponsor_type")
        sponsor_slug = self.request.query_params.get("sponsor_slug")
        forum_slug = self.request.query_params.get("forum_slug")

        if not sponsor_type or not sponsor_slug:
            return Discussion.objects.none()

        # Get the content type for the sponsor model
        try:
            if sponsor_type == "group":
                from groups.models import Group
                content_type = ContentType.objects.get_for_model(Group)
                sponsor = Group.objects.get(slug=sponsor_slug)
            elif sponsor_type == "member":
                from django.contrib.auth import get_user_model
                User = get_user_model()
                content_type = ContentType.objects.get_for_model(User)
                sponsor = User.objects.get(username=sponsor_slug)
            else:
                return Discussion.objects.none()
        except Exception:
            return Discussion.objects.none()

        # Base queryset: discussions in forums owned by this sponsor
        qs = Discussion.objects.filter(
            forum__sponsor_content_type=content_type,
            forum__sponsor_object_id=sponsor.id,
            is_deleted=False
        ).select_related(
            "forum",
            "created_by",
            "last_post"
        ).prefetch_related(
            "posts"
        )

        # Optional: filter to specific forum
        if forum_slug:
            qs = qs.filter(forum__slug=forum_slug)

        return qs.order_by("-updated_at")
