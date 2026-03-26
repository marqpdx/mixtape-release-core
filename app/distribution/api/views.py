# distribution/api/views.py
"""
Distribution API views.

POST   /api/writing/pieces/<piece_id>/distribute    — create + execute PublishEvent
DELETE /api/writing/pieces/<piece_id>/publish-events/<event_id>  — cancel scheduled event
GET    /api/writing/pieces/<piece_id>/distribution-history        — list PublishEvents + ShareRecords
GET    /api/distribution/sources                   — list available Sources
"""

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from distribution.models import PublishEvent, PublishEventStatus, Source
from distribution.services import (
    cancel_publish_event,
    create_publish_event,
    execute_publish_event,
    schedule_publish_event,
)
from writing.models import WritingPiece

from .serializers import (
    DistributeRequestSerializer,
    PublishEventSerializer,
    SourceSerializer,
)


class SourceListView(generics.ListAPIView):
    """
    GET /api/distribution/sources
    List all active Sources available to the authenticated user.
    Optional: ?group=<slug> to filter group-scoped sources.
    """
    serializer_class = SourceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Source.objects.filter(is_active=True)
        group_slug = self.request.query_params.get("group")
        if group_slug:
            qs = qs.filter(group__slug=group_slug)
        else:
            qs = qs.filter(group__isnull=True)
        return qs


class DistributeView(APIView):
    """
    POST /api/writing/pieces/<piece_id>/distribute

    Create and execute (or schedule) a PublishEvent for the given piece.

    The piece must already be published (status='published') before
    distribution can be triggered. External channels require that a
    canonical URL can be determined from the piece's slug.

    Payload:
    {
      "sources": [
        {"source_id": "<uuid>", "config": {"post_copy": "..."}},
        {"source_id": "<uuid>", "config": {"group_id": "<uuid>"}}
      ],
      "scheduled_at": null   // or ISO datetime for deferred execution
    }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, piece_id=None):
        piece = get_object_or_404(
            WritingPiece.objects.select_related("sponsor_content_type"),
            pk=piece_id,
            author=request.user,
        )

        if piece.status not in ("published", "scheduled"):
            return Response(
                {"detail": "Piece must be published before distribution."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = DistributeRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        event = create_publish_event(
            piece=piece,
            created_by=request.user,
            sources_config=ser.validated_data["sources"],
            scheduled_at=ser.validated_data.get("scheduled_at"),
        )

        if event.scheduled_at:
            schedule_publish_event(event)
        else:
            execute_publish_event(str(event.id))
            event.refresh_from_db()

        return Response(
            PublishEventSerializer(event).data,
            status=status.HTTP_201_CREATED,
        )


class PublishEventCancelView(APIView):
    """
    DELETE /api/writing/pieces/<piece_id>/publish-events/<event_id>
    Cancel a pending scheduled PublishEvent.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, piece_id=None, event_id=None):
        piece = get_object_or_404(WritingPiece, pk=piece_id, author=request.user)
        event = get_object_or_404(
            PublishEvent, id=event_id, writing_piece=piece
        )
        cancelled = cancel_publish_event(event)
        if not cancelled:
            return Response(
                {"detail": f"Cannot cancel event with status '{event.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DistributionHistoryView(generics.ListAPIView):
    """
    GET /api/writing/pieces/<piece_id>/distribution-history
    List all PublishEvents (with nested ShareRecords) for a piece.
    """
    serializer_class = PublishEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        piece = get_object_or_404(
            WritingPiece, pk=self.kwargs["piece_id"], author=self.request.user
        )
        return (
            PublishEvent.objects.filter(writing_piece=piece)
            .prefetch_related("share_records__source")
            .order_by("-created_at")
        )
