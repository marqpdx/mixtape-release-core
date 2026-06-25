# initiatives/api/views_me.py
#
# Member-facing personal initiative surface (MX-V6).
# All endpoints are IsAuthenticated only — no _superuser_required gate.
# Resolves the personal initiative via sponsor=user, is_personal=True.
# MemberStartupService guarantees this exists for every member at signup.

import json
import logging

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from initiatives.models import (
    ApertureLog,
    ApertureLogEntry,
    ApertureLogEntryKind,
    Artifact,
    Initiative,
    Note,
    QualityScanState,
    Session,
)
from initiatives.api.serializers import (
    ArtifactSerializer,
    InitiativeSerializer,
    NoteSerializer,
    SessionSerializer,
)

logger = logging.getLogger(__name__)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_personal_initiative(user):
    """Return the user's personal initiative. 404 means a data integrity gap."""
    user_ct = ContentType.objects.get_for_model(user.__class__)
    return get_object_or_404(
        Initiative,
        sponsor_content_type=user_ct,
        sponsor_object_id=user.pk,
        is_personal=True,
    )


# ---------------------------------------------------------------------------
# GET /api/initiatives/me
# ---------------------------------------------------------------------------

class MeInitiativeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        initiative = _get_personal_initiative(request.user)
        return Response(InitiativeSerializer(initiative).data)


# ---------------------------------------------------------------------------
# GET/POST /api/initiatives/me/sessions
# ---------------------------------------------------------------------------

class MeSessionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        initiative = _get_personal_initiative(request.user)
        sessions = initiative.sessions.all()
        return Response(SessionSerializer(sessions, many=True).data)

    def post(self, request):
        initiative = _get_personal_initiative(request.user)

        serializer = SessionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session = serializer.save(
            initiative=initiative,
            created_by=request.user,
            raw_transcript=[],
            distillation={},
        )
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# GET/PATCH /api/initiatives/me/sessions/<uuid:session_id>
# ---------------------------------------------------------------------------

class MeSessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, user, session_id):
        initiative = _get_personal_initiative(user)
        return get_object_or_404(Session, id=session_id, initiative=initiative)

    def get(self, request, session_id):
        session = self._get_session(request.user, session_id)
        return Response(SessionSerializer(session).data)

    def patch(self, request, session_id):
        session = self._get_session(request.user, session_id)

        if request.data.get("end") is True and session.ended_at is None:
            session.close()

        serializer = SessionSerializer(session, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# POST /api/initiatives/me/sessions/<uuid:session_id>/exchange
# ---------------------------------------------------------------------------

class MeSessionExchangeView(APIView):
    """
    POST a user turn; receive streaming AI response via SSE.

    Response is text/event-stream with delta chunks:
      data: {"type": "delta", "text": "..."}
      data: {"type": "done"}
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id):
        message = request.data.get("message", "").strip()
        if not message:
            return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

        initiative = _get_personal_initiative(request.user)
        session = get_object_or_404(Session, id=session_id, initiative=initiative)

        if session.ended_at:
            return Response(
                {"detail": "Session is already closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if message == "/run":
            return self._handle_run_command(initiative, request.user)

        try:
            from initiatives.ai.service import InitiativeAIService
            ai = InitiativeAIService()
        except Exception as exc:
            logger.error("me_exchange_ai_init_failed session=%s error=%s", session_id, exc)
            return Response(
                {"detail": "AI service is currently unavailable. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info("me_session_exchange_start session=%s user=%s", session_id, request.user.username)

        def stream():
            try:
                for chunk in ai.exchange_stream(initiative, session, message, request.user.username):
                    yield chunk
            except Exception:
                logger.exception("me_session_exchange_stream_error session=%s", session_id)
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

    def _handle_run_command(self, initiative, user):
        aperture_log, _ = ApertureLog.objects.get_or_create(initiative=initiative)

        last_boundary = (
            ApertureLogEntry.objects
            .filter(aperture_log=aperture_log, kind=ApertureLogEntryKind.RUN_BOUNDARY)
            .order_by("-created_at")
            .first()
        )
        if last_boundary:
            entry_count = ApertureLogEntry.objects.filter(
                aperture_log=aperture_log,
                created_at__gt=last_boundary.created_at,
            ).exclude(kind=ApertureLogEntryKind.RUN_BOUNDARY).count()
        else:
            entry_count = ApertureLogEntry.objects.filter(
                aperture_log=aperture_log,
            ).exclude(kind=ApertureLogEntryKind.RUN_BOUNDARY).count()

        now = timezone.now()
        label = f"Run — {now.strftime('%B %-d, %-I:%M%p').lower()} · {entry_count} {'entry' if entry_count == 1 else 'entries'}"

        ApertureLogEntry.objects.create(
            aperture_log=aperture_log,
            kind=ApertureLogEntryKind.RUN_BOUNDARY,
            body=label,
            is_system_generated=True,
            authored_by="system",
        )

        def stream():
            yield (
                b"data: "
                + json.dumps({"type": "delta", "text": f"— {label} —\n\nRun closed. Start typing to begin a new run."}).encode()
                + b"\n\n"
            )
            yield b"data: " + json.dumps({"type": "done"}).encode() + b"\n\n"

        return StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


# ---------------------------------------------------------------------------
# GET /api/initiatives/me/sessions/<uuid:session_id>/artifacts
# ---------------------------------------------------------------------------

class MeArtifactListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id):
        initiative = _get_personal_initiative(request.user)
        session = get_object_or_404(Session, id=session_id, initiative=initiative)
        artifacts = Artifact.objects.filter(initiative=initiative, session=session)
        kind_filter = request.query_params.get("kind")
        if kind_filter:
            artifacts = artifacts.filter(kind=kind_filter)
        return Response(ArtifactSerializer(artifacts, many=True).data)


# ---------------------------------------------------------------------------
# POST /api/initiatives/me/notes
# ---------------------------------------------------------------------------

class MeNoteCreateView(APIView):
    """
    Create a note attached to the user's personal initiative.
    Client does not need to know the initiative ID — resolved server-side.
    Used by MX-3 "Uplift to Build" exit.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        initiative = _get_personal_initiative(request.user)

        data = {**request.data, "initiative_id": str(initiative.id)}
        serializer = NoteSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.save(created_by=request.user)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)
