# atrium/api/views.py

from django.db.models import Count

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from atrium.models import AtriumSession
from .serializers import AtriumSessionListSerializer


class AtriumSessionListView(generics.ListAPIView):
    """
    GET /api/atrium/sessions/

    Returns the authenticated member's AtriumSessions, active-first then
    by most-recent activity, capped at 50. Annotates entry_count for
    the session list panel.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AtriumSessionListSerializer

    def get_queryset(self):
        profile = self.request.user.userprofile
        return (
            AtriumSession.objects.filter(
                member=profile,
                deleted_at__isnull=True,
            )
            .annotate(entry_count=Count("entries"))
            .order_by("status", "-last_activity_at", "-created_at")[:50]
        )
