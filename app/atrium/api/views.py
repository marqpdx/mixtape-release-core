# atrium/api/views.py

import json
import logging

from django.db.models import Count
from django.http import StreamingHttpResponse

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from atrium.models import AtriumSession, AtriumSessionStatus, AtriumSessionRole, Distillate, DistillateDocumentType
from atrium.ai.service import PUDDLEJUMP_GROUPS
from profiles.services.profiles import ensure_user_profile
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
        profile = ensure_user_profile(self.request.user)
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
        profile = ensure_user_profile(request.user)

        sponsor_ct = None
        sponsor_id = None
        group_slug = request.data.get("group_slug", "")
        if group_slug:
            from django.contrib.contenttypes.models import ContentType
            from groups.models.group import Group
            group = Group.objects.filter(slug=group_slug, deleted_at__isnull=True).first()
            if group:
                sponsor_ct = ContentType.objects.get_for_model(Group)
                sponsor_id = group.pk

        session = AtriumSession.objects.create(
            member=profile,
            title=request.data.get("title", ""),
            session_context=request.data.get("session_context", ""),
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_id,
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

        profile = ensure_user_profile(self.request.user)
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
        profile = ensure_user_profile(request.user)

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
        profile = ensure_user_profile(request.user)

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
        if "dial_mode" in request.data:
            from atrium.models import AtriumDialMode
            val = request.data["dial_mode"]
            valid_values = {m.value for m in AtriumDialMode}
            if val in valid_values:
                session.dial_mode = val
                update_fields.append("dial_mode")

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
        profile = ensure_user_profile(request.user)

        try:
            session = AtriumSession.objects.select_related("sponsor_content_type").get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # Puddlejump-gated groups require staff access.
        if session.sponsor_object_id:
            sponsor = session.sponsor
            sponsor_slug = getattr(sponsor, "slug", None)
            if sponsor_slug in PUDDLEJUMP_GROUPS and not request.user.is_staff:
                return Response(
                    {"detail": "Staff access required for this group's Atrium."},
                    status=status.HTTP_403_FORBIDDEN,
                )

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
            ai = AtriumAIService(session=session)
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


class AtriumSessionWarmView(APIView):
    """
    POST /api/atrium/sessions/<session_id>/warm

    Pre-warms the PTY subprocess for a ClaudeCode session so the first
    exchange is fast. Returns a text/event-stream with a single `type: ready`
    event. Non-error for Anthropic-SDK sessions — just returns ready immediately.

    Called by the frontend when the user opens or selects a session.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        profile = ensure_user_profile(request.user)

        try:
            session = AtriumSession.objects.select_related("sponsor_content_type").get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        if session.sponsor_object_id:
            sponsor_slug = getattr(session.sponsor, "slug", None)
            if sponsor_slug in PUDDLEJUMP_GROUPS and not request.user.is_staff:
                return Response(
                    {"detail": "Staff access required for this group's Atrium."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            from atrium.ai.service import AtriumAIService
            ai = AtriumAIService(session=session)
        except Exception as exc:
            logger.error("atrium_warm_init_failed session=%s error=%s", session_id, exc)
            return Response({"detail": "AI service unavailable."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        logger.info("atrium_warm session=%s user=%s", session_id, request.user.username)

        return StreamingHttpResponse(
            ai.warm(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


class AtriumSessionCompactView(APIView):
    """
    POST /api/atrium/sessions/<session_id>/compact

    Sends /compact to the session's PTY subprocess. Stores the resulting
    summary in ApertureLog.compact_summary. Returns:
      { "summary": "..." }  on success
      { "detail": "..." }   on error/no PTY
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        profile = ensure_user_profile(request.user)

        try:
            session = AtriumSession.objects.select_related("sponsor_content_type").get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        if session.sponsor_object_id:
            sponsor_slug = getattr(session.sponsor, "slug", None)
            if sponsor_slug in PUDDLEJUMP_GROUPS and not request.user.is_staff:
                return Response(
                    {"detail": "Staff access required for this group's Atrium."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            from atrium.ai.service import AtriumAIService
            ai = AtriumAIService(session=session)
            summary = ai.compact(session)
        except Exception as exc:
            logger.error("atrium_compact_failed session=%s error=%s", session_id, exc)
            return Response({"detail": "Compact failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"summary": summary}, status=status.HTTP_200_OK)


class AtriumSessionDistillView(APIView):
    """
    POST /api/atrium/sessions/<session_id>/distill

    Generate a Distillate artifact from the session's conversation history.
    Uses a one-shot `claude -p` call (same pattern as the Continuous Keeper)
    with a prompt that asks Claude to produce a named document of the given type.

    Body: { "title": str, "document_type": str }
    Returns: { "id", "title", "body", "document_type", "created_at" }
    """

    permission_classes = [IsAuthenticated]

    _DISTILL_PROMPT_TEMPLATE = """\
You are a knowledge distiller. The following is a transcript of an AI-assisted \
work session titled "{title}". Produce a {document_type_label} document with \
the title "{title}".

Guidelines for a {document_type_label}:
{document_type_guidance}

Session transcript:
{transcript}

Write only the document body — no title heading, no preamble. Use markdown.
"""

    _DOCUMENT_TYPE_GUIDANCE = {
        DistillateDocumentType.FIELD_NOTE: (
            "A field note is a short (1-3 paragraphs), direct record of what was observed, "
            "decided, or learned. First-person voice. What happened, what was noticed, what's next."
        ),
        DistillateDocumentType.FINDING: (
            "A finding states a conclusion derived from evidence. Structured: Background, "
            "Evidence, Finding, Implication. Precise and factual — no hedging."
        ),
        DistillateDocumentType.POSITION_PAPER: (
            "A position paper argues for a specific approach or decision. Structured: "
            "Context, Position, Rationale, Trade-offs, Recommendation."
        ),
        DistillateDocumentType.DRAFT_ADR: (
            "An ADR (Architecture Decision Record) documents a decision and its context. "
            "Sections: Status (Draft), Context, Decision, Consequences."
        ),
        DistillateDocumentType.SUMMARY: (
            "A summary captures the key points, decisions, and open questions from the session "
            "in 2-4 paragraphs. Concise and scannable — bullet lists welcome."
        ),
        DistillateDocumentType.OTHER: (
            "Produce a clear, well-structured document that captures the key substance of the session."
        ),
    }

    _MAX_TRANSCRIPT_CHARS = 40_000

    def post(self, request, session_id):
        profile = ensure_user_profile(request.user)

        try:
            session = AtriumSession.objects.select_related("sponsor_content_type").get(
                id=session_id,
                member=profile,
                deleted_at__isnull=True,
            )
        except AtriumSession.DoesNotExist:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        title = (request.data.get("title") or "").strip()
        document_type = (request.data.get("document_type") or DistillateDocumentType.SUMMARY)

        if not title:
            return Response({"detail": "title is required."}, status=status.HTTP_400_BAD_REQUEST)

        if document_type not in DistillateDocumentType.values:
            return Response(
                {"detail": f"document_type must be one of: {', '.join(DistillateDocumentType.values)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve initiative via sponsor GFK (same pattern as _resolve_aperture_log)
        from atrium.ai.service import _resolve_aperture_log
        log, _ = _resolve_aperture_log(session)
        if log is None:
            return Response(
                {"detail": "No initiative found for this session — Distillate requires an initiative context."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Build transcript from session entries
        entries = list(session.entries.order_by("created_at"))
        lines = []
        for entry in entries:
            role_label = "User" if entry.role == AtriumSessionRole.USER else "Assistant"
            lines.append(f"{role_label}: {entry.content.strip()}")
        transcript = "\n".join(lines)
        if len(transcript) > self._MAX_TRANSCRIPT_CHARS:
            transcript = transcript[-self._MAX_TRANSCRIPT_CHARS:]

        if not transcript:
            return Response(
                {"detail": "Session has no entries to distill."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        document_type_label = dict(DistillateDocumentType.choices).get(document_type, document_type)
        guidance = self._DOCUMENT_TYPE_GUIDANCE.get(document_type, self._DOCUMENT_TYPE_GUIDANCE[DistillateDocumentType.OTHER])

        prompt = self._DISTILL_PROMPT_TEMPLATE.format(
            title=title,
            document_type_label=document_type_label,
            document_type_guidance=guidance,
            transcript=transcript,
        )

        from atrium.tasks import _run_claude_p
        body = _run_claude_p(prompt)
        if not body:
            logger.error("atrium_distill_failed session=%s — claude -p returned empty", session_id)
            return Response({"detail": "Distillate generation failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        distillate = Distillate.objects.create(
            initiative=log.initiative,
            session=session,
            title=title,
            body=body,
            document_type=document_type,
        )

        logger.info(
            "atrium_distill session=%s distillate=%s type=%s",
            session_id, distillate.id, document_type,
        )

        return Response(
            {
                "id": str(distillate.id),
                "title": distillate.title,
                "body": distillate.body,
                "document_type": distillate.document_type,
                "created_at": distillate.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
