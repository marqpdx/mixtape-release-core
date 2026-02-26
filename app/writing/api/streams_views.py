# writing/api/streams_views.py

from rest_framework import generics, permissions

from fundamentals.services.follow_service import get_following_ids
from writing.models import Leaf

from .serializers import LeafSerializer


class StreamsView(generics.ListAPIView):
    """
    GET /api/writing/streams → chronological feed from followed users.
    No algorithmic logic. Pure chronological from explicit follows.
    """
    serializer_class = LeafSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        following_ids = get_following_ids(self.request.user)
        return Leaf.objects.filter(
            author_id__in=following_ids,
            visibility="public",
            published_at__isnull=False,
            deleted_at__isnull=True,
        ).select_related(
            "author", "author__profile", "source_content_type",
        ).order_by("-published_at")
