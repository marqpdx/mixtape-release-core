# atrium/api/views.py

import json
import logging

from django.db.models import Count
from django.http import StreamingHttpResponse

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from atrium.models import AtriumSession, AtriumSessionStatus
from .serializers import AtriumSessionListSerializer, AtriumSessionEntrySerializer

logger = logging.getLogger(__name__)


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


class AtriumSessionCreateView(generics.CreateAPIView):
    """
    POST /api/atrium/sessions/

    Creates a new AtriumSession for the authenticated member.
    Body: { title?: string, session_context?: string }
    """

    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        profile = request.user.userprofile
        session = AtriumSession.objects.create(
            member=profile,
            title=request.data.get("title", ""),
            session_context=request.data.get("session_context", ""),
        )
        return Response(
            AtriumSessionListSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class AtriumSessionEntryListView(generics.ListAPIView):
    """
    GET /api/atrium/sessions/<session_id>/entries/

    Returns the persisted AtriumSessionEntry records for a session, in
    chronological order. Used to restore conversation history when a
    member reopens an existing session, and as the source for MillDraft
    promotion (artifact landing, AT-D6).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = AtriumSessionEntrySerializer

    def get_queryset(self):
        from atrium.models import AtriumSessionEntry

        profile = self.request.user.userprofile
        session_id = self.kwargs["session_id"]
        return AtriumSessionEntry.objects.filter(
            session_id=session_id,
            session__member=profile,
            session__deleted_at__isnull=True,
        ).order_by("created_at")


class AtriumSessionContextView(APIView):
    """
    GET /api/atrium/sessions/<session_id>/context/

    Returns the synthesized Beryl personal context that will be injected into
    the system prompt for this session. Surfaces to the member as a preview
    panel — transparent about what Claude knows before each exchange.

    Response: { context: string, sources: string[] }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        profile = request.user.userprofile

        try:
            session = AtriumSession.objects.get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        from atrium.ai.context import BerylPersonalContextBuilder
        builder = BerylPersonalContextBuilder()
        return Response({
            "context": builder.build(session),
            "sources": builder.sources(session),
        })


class AtriumSessionUpdateView(APIView):
    """
    PATCH /api/atrium/sessions/<session_id>/

    Updates title and/or session_context on an AtriumSession.
    Body: { title?: string, session_context?: string }
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, session_id):
        profile = request.user.userprofile

        try:
            session = AtriumSession.objects.get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        update_fields = []
        if "title" in request.data:
            session.title = request.data["title"]
            update_fields.append("title")
        if "session_context" in request.data:
            session.session_context = request.data["session_context"]
            update_fields.append("session_context")

        if update_fields:
            session.save(update_fields=update_fields)

        return Response(
            AtriumSessionListSerializer(session).data,
            status=status.HTTP_200_OK,
        )


class AtriumSessionExchangeView(APIView):
    """
    POST /api/atrium/sessions/<session_id>/exchange

    Streams a Claude API response for the given user message.
    Creates AtriumSessionEntry records for both turns.

    Body: { message: string }
    Response: text/event-stream SSE
      data: {"type": "delta", "text": "..."}
      data: {"type": "done"}
      data: {"type": "error", "detail": "..."}  (on failure)
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        profile = request.user.userprofile

        try:
            session = AtriumSession.objects.get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        if session.status == AtriumSessionStatus.ARCHIVED:
            return Response(
                {"detail": "Session is archived."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from atrium.ai.service import AtriumAIService
            ai = AtriumAIService()
        except Exception as exc:
            logger.error("atrium_ai_service_init_failed session=%s error=%s", session_id, exc)
            return Response(
                {"detail": "AI service is currently unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info("atrium_exchange_start session=%s user=%s", session_id, request.user.username)

        def stream():
            try:
                for chunk in ai.exchange_stream(session, message):
                    yield chunk
            except Exception:
                logger.exception("atrium_exchange_stream_error session=%s", session_id)
                yield (
                    b"data: "
                    + json.dumps({"type": "error", "detail": "An error occurred during the AI exchange."}).encode()
                    + b"\n\n"
                )

        return StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
