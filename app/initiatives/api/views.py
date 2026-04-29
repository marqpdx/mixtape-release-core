# initiatives/api/views.py

import logging

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import parsers, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from django.contrib.contenttypes.models import ContentType
from initiatives.models import (
    AgentCommand,
    AgentCommandStatus,
    ActionRun,
    Artifact,
    ApertureLog,
    ApertureLogEntry,
    ApertureLogEntryKind,
    ArtifactKind,
    DistillationState,
    Initiative,
    InitiativeStatus,
    Note,
    Reminder,
    QualityScanState,
    Session,
    Task,
)
from initiatives.api.serializers import (
    AgentCommandDetailSerializer,
    ActionRunCreateSerializer,
    ActionRunDetailSerializer,
    ActionRunPatchSerializer,
    ActionRunSummarySerializer,
    ApertureLogEntrySerializer,
    ApertureLogSerializer,
    ArtifactSerializer,
    DistillationCurateSerializer,
    InitiativeSerializer,
    LinkedOutputCreateSerializer,
    serialize_linked_output,
    MobileCommandConfirmSerializer,
    MobileCommandCreateSerializer,
    NoteSerializer,
    ReminderSerializer,
    RollingSummaryUpdateSerializer,
    SessionSerializer,
    TaskSerializer,
)
from initiatives.api.permissions import HasOrchestrationWriteScope
from livewire.auth import InternalServiceAuthentication
from initiatives.services import (
    AgentParseError,
    execute_agent_command,
    parse_agent_command,
    resolve_content_type_for_sponsor_model,
    summarize_parsed_command,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission helper
# ---------------------------------------------------------------------------

def _superuser_required(request):
    """v0: Initiatives are superuser-only. Returns True if allowed."""
    return request.user.is_superuser


def _get_group(slug):
    return get_object_or_404(Group, slug=slug)


# ---------------------------------------------------------------------------
# Initiative CRUD
# ---------------------------------------------------------------------------

class InitiativeListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)

        qs = Initiative.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            parent__isnull=True,  # Root initiatives only; threads accessed via /threads/
        ).prefetch_related("sessions").select_related("created_by")

        # Resolved and archived are hidden by default; pass include_resolved=true to show both
        include_resolved = request.query_params.get("include_resolved") == "true"
        if not include_resolved:
            qs = qs.exclude(status__in=[InitiativeStatus.RESOLVED, InitiativeStatus.ARCHIVED])

        serializer = InitiativeSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request, slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)

        serializer = InitiativeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        initiative = serializer.save(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            created_by=request.user,
            rolling_summary={
                "current_direction": "",
                "key_decisions": [],
                "open_questions": [],
                "where_we_are_now": "",
            },
        )
        return Response(InitiativeSerializer(initiative).data, status=status.HTTP_201_CREATED)


class InitiativeDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return Response(InitiativeSerializer(initiative).data)

    def patch(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        serializer = InitiativeSerializer(initiative, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        initiative.deleted_at = timezone.now()
        initiative.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Rolling Summary
# ---------------------------------------------------------------------------

class RollingSummaryView(APIView):
    """PATCH to update specific fields of the rolling summary."""
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

        serializer = RollingSummaryUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        current = initiative.rolling_summary_display
        current.update({k: v for k, v in serializer.validated_data.items()})
        initiative.rolling_summary = current
        initiative.rolling_summary_updated_at = timezone.now()
        initiative.rolling_summary_updated_by = request.user.username
        initiative.save(update_fields=[
            "rolling_summary",
            "rolling_summary_updated_at",
            "rolling_summary_updated_by",
            "updated_at",
        ])
        return Response({"rolling_summary": initiative.rolling_summary_display})


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_initiative(self, slug, initiative_id):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(slug, initiative_id)
        sessions = initiative.sessions.all()
        return Response(SessionSerializer(sessions, many=True).data)

    def post(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(slug, initiative_id)

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


class ActionRunListCreateView(APIView):
    authentication_classes = [InternalServiceAuthentication]
    permission_classes = [HasOrchestrationWriteScope]

    def post(self, request):
        serializer = ActionRunCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        action_run = serializer.save()
        return Response(ActionRunSummarySerializer(action_run).data, status=status.HTTP_201_CREATED)


class ActionRunDetailView(APIView):
    def get_authenticators(self):
        if self.request.method == "PATCH":
            return [InternalServiceAuthentication()]
        return super().get_authenticators()

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [HasOrchestrationWriteScope()]
        return [permissions.IsAuthenticated()]

    def get(self, request, action_run_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        action_run = get_object_or_404(ActionRun, pk=action_run_id)
        return Response(ActionRunDetailSerializer(action_run).data)

    def patch(self, request, action_run_id):
        action_run = get_object_or_404(ActionRun, pk=action_run_id)
        serializer = ActionRunPatchSerializer(action_run, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        updated = serializer.save()
        return Response(ActionRunSummarySerializer(updated).data)


def _resolve_mobile_command_target(*, initiative_id=None, sponsor_model=None, sponsor_id=None):
    initiative = None
    sponsor_content_type = None
    sponsor_object_id = None

    if initiative_id:
        initiative = get_object_or_404(Initiative, pk=initiative_id)
        sponsor_content_type = initiative.sponsor_content_type
        sponsor_object_id = initiative.sponsor_object_id
    elif sponsor_model and sponsor_id:
        sponsor_content_type = resolve_content_type_for_sponsor_model(sponsor_model)
        model_class = sponsor_content_type.model_class()
        if model_class is None:
            raise ValueError("Sponsor model is not concrete.")
        get_object_or_404(model_class, pk=sponsor_id)
        sponsor_object_id = sponsor_id

    return initiative, sponsor_content_type, sponsor_object_id


class MobileCommandListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        serializer = MobileCommandCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            parsed = parse_agent_command(
                text=data["text"],
                capture_mode=data["capture_mode"],
                source=data["source"],
                initiative_id=data.get("initiative_id"),
                sponsor_model=data.get("sponsor_model"),
                sponsor_id=data.get("sponsor_id"),
                principal_user_id=request.user.pk,
            )
        except AgentParseError as exc:
            http_status = (
                status.HTTP_504_GATEWAY_TIMEOUT
                if exc.status_code == 504
                else status.HTTP_502_BAD_GATEWAY
            )
            body = {"detail": exc.detail}
            if exc.body:
                body["body"] = exc.body
            return Response(body, status=http_status)

        title, summary, generated_text, needs_clarification, clarification_reason = summarize_parsed_command(parsed)
        try:
            initiative, sponsor_content_type, sponsor_object_id = _resolve_mobile_command_target(
                initiative_id=data.get("initiative_id"),
                sponsor_model=data.get("sponsor_model"),
                sponsor_id=data.get("sponsor_id"),
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        command = AgentCommand.objects.create(
            initiative=initiative,
            sponsor_content_type=sponsor_content_type,
            sponsor_object_id=sponsor_object_id,
            source=data["source"],
            capture_mode=data["capture_mode"],
            draft_session_id=data.get("draft_id") or data.get("session_id") or "",
            raw_input=data["text"],
            parsed_verb=parsed.get("verb") or "",
            confidence=parsed.get("confidence"),
            parsed_title=title,
            parsed_summary=summary,
            parsed_fields=parsed.get("normalized_payload") or {},
            parse_metadata={
                "parsed_entities": parsed.get("parsed_entities") or {},
                "ambiguities": parsed.get("ambiguities") or [],
                "method": parsed.get("method") or "llm",
            },
            generated_text=generated_text,
            needs_clarification=needs_clarification,
            clarification_reason=clarification_reason,
            created_by=request.user,
        )
        return Response(AgentCommandDetailSerializer(command).data, status=status.HTTP_201_CREATED)


class MobileCommandDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, command_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        command = get_object_or_404(AgentCommand, pk=command_id)
        return Response(AgentCommandDetailSerializer(command).data)


class MobileCommandConfirmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, command_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        command = get_object_or_404(AgentCommand, pk=command_id)
        if command.status != AgentCommandStatus.PARSED:
            return Response(
                {"detail": f"Command is not confirmable in status '{command.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MobileCommandConfirmSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            command = execute_agent_command(
                command=command,
                confirmed_fields=serializer.validated_data.get("fields") or {},
                confirmed_by=request.user,
            )
        except NotImplementedError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_501_NOT_IMPLEMENTED)

        return Response(AgentCommandDetailSerializer(command).data)


class NoteListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        serializer = NoteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.save(created_by=request.user)
        return Response(NoteSerializer(note).data, status=status.HTTP_201_CREATED)


class NoteDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, note_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        note = get_object_or_404(Note, pk=note_id)
        return Response(NoteSerializer(note).data)


class GroupReminderListView(APIView):
    """GET /api/initiatives/groups/{slug}/reminders — all pending reminders for a group."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)

        qs = Reminder.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        ).exclude(status="acknowledged")

        serializer = ReminderSerializer(qs, many=True)
        return Response(serializer.data)


class GroupTaskListView(APIView):
    """GET /api/initiatives/groups/{slug}/tasks — open tasks for a group."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)

        qs = Task.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
            deleted_at__isnull=True,
        ).exclude(status="done")

        serializer = TaskSerializer(qs, many=True)
        return Response(serializer.data)


class ReminderListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ReminderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reminder = serializer.save(created_by=request.user)
        return Response(ReminderSerializer(reminder).data, status=status.HTTP_201_CREATED)


class ReminderDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, reminder_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        reminder = get_object_or_404(Reminder, pk=reminder_id)
        return Response(ReminderSerializer(reminder).data)


class TaskListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TaskSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        task = serializer.save(created_by=request.user)
        return Response(TaskSerializer(task).data, status=status.HTTP_201_CREATED)


class TaskDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, task_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        task = get_object_or_404(Task, pk=task_id)
        return Response(TaskSerializer(task).data)


class SessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, slug, initiative_id, session_id):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return get_object_or_404(Session, id=session_id, initiative=initiative)

    def get(self, request, slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        session = self._get_session(slug, initiative_id, session_id)
        return Response(SessionSerializer(session).data)

    def patch(self, request, slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        session = self._get_session(slug, initiative_id, session_id)

        # Handle end: true to close the session
        if request.data.get("end") is True and session.ended_at is None:
            session.close()

        serializer = SessionSerializer(session, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Session Exchange (AI streaming) — stub
# ---------------------------------------------------------------------------

class SessionExchangeView(APIView):
    """
    POST a user turn; receive streaming AI response via SSE.

    Response is text/event-stream with delta chunks:
      data: {"type": "delta", "text": "..."}
      data: {"type": "done"}

    Falls back to a plain JSON 200 with the full response if streaming fails.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get("message", "").strip()
        if not message:
            return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        session = get_object_or_404(Session, id=session_id, initiative=initiative)

        if session.ended_at:
            return Response(
                {"detail": "Session is already closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # /run command — insert run_boundary ApertureLog entry; do not pass to AI
        if message == "/run":
            return self._handle_run_command(initiative, request.user)

        try:
            from initiatives.ai.service import InitiativeAIService
            ai = InitiativeAIService()
        except Exception as exc:
            logger.error("ai_service_init_failed session=%s error=%s", session_id, exc)
            return Response(
                {"detail": "AI service is currently unavailable. Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info("session_exchange_start session=%s user=%s", session_id, request.user.username)

        def stream():
            try:
                for chunk in ai.exchange_stream(initiative, session, message, request.user.username):
                    yield chunk
            except Exception:
                import json as _json
                logger.exception("session_exchange_stream_error session=%s", session_id)
                yield (
                    b"data: "
                    + _json.dumps({"type": "error", "detail": "An error occurred during the AI exchange."}).encode()
                    + b"\n\n"
                )

        return StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    def _handle_run_command(self, initiative, user):
        """
        Insert a run_boundary ApertureLog entry and return a system SSE response.
        The entry carries a label with timestamp and entry count since the last boundary.
        """
        import json as _json
        from django.utils import timezone
        from initiatives.models import ApertureLog, ApertureLogEntry, ApertureLogEntryKind

        aperture_log, _ = ApertureLog.objects.get_or_create(initiative=initiative)

        # Count entries since the last run_boundary (or all entries if none)
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
                + _json.dumps({"type": "delta", "text": f"— {label} —\n\nRun closed. Start typing to begin a new run."}).encode()
                + b"\n\n"
            )
            yield b"data: " + _json.dumps({"type": "done"}).encode() + b"\n\n"

        return StreamingHttpResponse(
            stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------

class ProposeDistillationView(APIView):
    """
    POST to trigger AI distillation proposal for a closed session.
    Full implementation in AI integration pass.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        session = get_object_or_404(Session, id=session_id, initiative=initiative)

        if session.ended_at is None:
            return Response(
                {"detail": "Close the session before proposing distillation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if session.distillation_state == DistillationState.CURATED:
            return Response(
                {"detail": "Distillation already curated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Call AI service; fall back to empty scaffold on failure
        try:
            from initiatives.ai.service import InitiativeAIService
            ai = InitiativeAIService()
            distillation = ai.propose_distillation(initiative, session)
        except Exception as exc:
            logger.warning("ai_distillation_unavailable session=%s error=%s", session_id, exc)
            distillation = {
                "decisions": [],
                "open_questions": [],
                "actions": [],
                "notes": "(AI unavailable — fill in manually.)",
            }

        session.distillation = distillation
        session.distillation_state = DistillationState.PROPOSED
        session.save(update_fields=["distillation", "distillation_state", "updated_at"])

        logger.info("distillation_proposed session=%s", session_id)
        return Response(SessionSerializer(session).data)


class CommitDistillationView(APIView):
    """
    POST user's curated distillation. Finalises the session and triggers
    a rolling summary update task.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        session = get_object_or_404(Session, id=session_id, initiative=initiative)

        if session.distillation_state not in (DistillationState.PROPOSED, DistillationState.PENDING):
            return Response(
                {"detail": "Nothing to commit."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DistillationCurateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session.distillation = serializer.validated_data
        session.distillation_state = DistillationState.CURATED
        session.save(update_fields=["distillation", "distillation_state", "updated_at"])

        # Trigger async rolling summary update
        from initiatives.tasks import update_rolling_summary
        update_rolling_summary.delay(str(initiative.id), str(session.id))

        logger.info("distillation_committed session=%s initiative=%s", session_id, initiative_id)
        return Response(SessionSerializer(session).data)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class ArtifactListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_initiative(self, slug, initiative_id):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(slug, initiative_id)
        artifacts = initiative.artifacts.all()
        kind_filter = request.query_params.get("kind")
        if kind_filter:
            artifacts = artifacts.filter(kind=kind_filter)
        return Response(ArtifactSerializer(artifacts, many=True).data)

    def post(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(slug, initiative_id)

        serializer = ArtifactSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        artifact = serializer.save(initiative=initiative)

        # Direct Annotations get an async quality scan
        if artifact.is_direct_annotation:
            from initiatives.tasks import run_artifact_quality_scan
            run_artifact_quality_scan.delay(str(artifact.id))
        else:
            artifact.quality_scan_state = QualityScanState.SKIPPED
            artifact.save(update_fields=["quality_scan_state"])

        return Response(ArtifactSerializer(artifact).data, status=status.HTTP_201_CREATED)


class ArtifactDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_artifact(self, slug, initiative_id, artifact_id):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return get_object_or_404(Artifact, id=artifact_id, initiative=initiative)

    def patch(self, request, slug, initiative_id, artifact_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        artifact = self._get_artifact(slug, initiative_id, artifact_id)
        serializer = ArtifactSerializer(artifact, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


class ArtifactRouteToPuddlejumpView(APIView):
    """
    POST to submit an artifact to Puddlejump as a candidate doc.
    Creates the candidate record and marks the artifact as routed.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id, artifact_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        artifact = get_object_or_404(Artifact, id=artifact_id, initiative=initiative)

        if artifact.puddlejump_routed:
            return Response(
                {"detail": "Already routed to Puddlejump."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TODO: Create candidate doc record in Puddlejump DB
        # For now, mark as routed and return formatted document
        artifact.route_to_puddlejump()

        # Format as Puddlejump-compatible Markdown candidate
        doc_content = _format_as_puddlejump_doc(artifact, initiative)

        logger.info("artifact_routed_to_puddlejump artifact=%s initiative=%s", artifact_id, initiative_id)
        return Response({
            "artifact": ArtifactSerializer(artifact).data,
            "document": doc_content,
            "message": "Artifact submitted to Puddlejump as candidate. Review and download to filesystem to make it official.",
        })


def _format_as_puddlejump_doc(artifact, initiative) -> str:
    """Format an artifact as a Puddlejump-compatible Markdown document."""
    from django.utils import timezone as tz
    today = tz.now().strftime("%Y-%m-%d")
    return f"""> **Status:** Draft — Canon Candidate
> **Class:** spec
> **Audit:** conceptual
> **Library:** features/initiatives
> **Source:** Initiative — {initiative.title}
> **Session:** {"Direct Annotation" if artifact.is_direct_annotation else str(artifact.session_id)}
> **Last Updated:** {today}

---

# {artifact.title}

{artifact.body}
"""


# ---------------------------------------------------------------------------
# Linked Outputs
# ---------------------------------------------------------------------------

class LinkedOutputListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_initiative(self, slug, initiative_id):
        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        from relations.service import RelationshipService
        initiative = self._get_initiative(slug, initiative_id)
        outputs = RelationshipService.get_outgoing(initiative, type_slug="outputs-from")
        return Response([serialize_linked_output(r) for r in outputs])

    def post(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        from django.contrib.contenttypes.models import ContentType
        from relations.service import RelationshipService

        initiative = self._get_initiative(slug, initiative_id)
        serializer = LinkedOutputCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        target_ct = get_object_or_404(ContentType, pk=data["output_content_type_id"])
        target_model = target_ct.model_class()
        if target_model is None:
            return Response({"detail": "Invalid content type."}, status=status.HTTP_400_BAD_REQUEST)
        target_obj = get_object_or_404(target_model, pk=data["output_object_id"])

        relationship = RelationshipService.create_relationship(
            type_slug="outputs-from",
            source=initiative,
            target=target_obj,
            created_by=request.user,
            notes=data.get("note", ""),
        )
        return Response(serialize_linked_output(relationship), status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Session Import — Preview
# ---------------------------------------------------------------------------

class ImportSessionPreviewView(APIView):
    """
    POST a JSON file (multipart or raw JSON body) to get a preview of what
    will be imported: parsed turns + heuristically detected artifacts.

    Nothing is written to the database at this stage.

    Accepts:
      multipart/form-data  with field "file" (application/json)
      application/json     with the raw export payload as the body
                           (useful for testing; large exports should use multipart)

    Query param:
      ?format=claude|chatgpt|freeform   (optional — auto-detected if omitted)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

        import json as _json
        from initiatives.importers.freeform_parser import auto_parse
        from initiatives.importers.base import ImportParseError

        # --- Load JSON data ---
        fmt = request.query_params.get("format", "").lower()
        try:
            data = _load_json_from_request(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # --- Parse ---
        try:
            if fmt == "claude":
                from initiatives.importers.claude_parser import parse
                parsed = parse(data)
            elif fmt == "chatgpt":
                from initiatives.importers.chatgpt_parser import parse
                parsed = parse(data)
            else:
                parsed = auto_parse(data)
        except ImportParseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except Exception:
            logger.exception("import_preview_failed initiative=%s", initiative_id)
            return Response(
                {"detail": "Failed to parse the JSON file. Check the format and try again."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(parsed.to_preview_dict())


# ---------------------------------------------------------------------------
# Session Import — Confirm
# ---------------------------------------------------------------------------

class ImportSessionConfirmView(APIView):
    """
    POST to create a Session from a previously previewed import.

    Body:
    {
      "title":          string (optional — overrides parsed title),
      "session_intent": "open_inquiry" | ... (optional, default open_inquiry),
      "turns":          [...],   // from preview response — written as raw_transcript
      "artifacts":      [        // user-reviewed list from preview
        {"kind": "decision"|"question"|"action"|"annotation"|"document",
         "title": "...",
         "body":  "..."}
      ]
    }

    Creates:
      - Session (capture_mode=imported, distillation_state=curated)
      - Artifact rows linked to the session
      - Fires update_rolling_summary task (async)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

        turns = request.data.get("turns") or []
        artifact_specs = request.data.get("artifacts") or []
        session_intent = request.data.get("session_intent", "open_inquiry")

        if not isinstance(turns, list):
            return Response({"detail": "turns must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        valid_intents = [c[0] for c in Session._meta.get_field("intent").choices]
        if session_intent not in valid_intents:
            session_intent = "open_inquiry"

        from initiatives.models import CaptureMode, DistillationState

        # --- Build distillation from confirmed artifacts ---
        distillation = _artifacts_to_distillation(artifact_specs)

        # --- Create Session ---
        session = Session.objects.create(
            initiative=initiative,
            intent=session_intent,
            capture_mode=CaptureMode.IMPORTED,
            raw_transcript=turns,
            distillation=distillation,
            distillation_state=DistillationState.CURATED,
            created_by=request.user,
            ended_at=timezone.now(),
        )

        # --- Create Artifacts ---
        created_artifacts = []
        valid_kinds = {c[0] for c in Artifact._meta.get_field("kind").choices}
        for spec in artifact_specs:
            kind = spec.get("kind") or "annotation"
            if kind not in valid_kinds:
                kind = "annotation"
            title = (spec.get("title") or "").strip()
            if not title:
                continue
            artifact = Artifact.objects.create(
                initiative=initiative,
                session=session,
                kind=kind,
                title=title,
                body=(spec.get("body") or "").strip(),
                quality_scan_state=QualityScanState.SKIPPED,
            )
            created_artifacts.append(artifact)

        # --- Fire async rolling summary update ---
        from initiatives.tasks import update_rolling_summary
        update_rolling_summary.delay(str(initiative.id), str(session.id))

        logger.info(
            "import_session_confirmed initiative=%s session=%s turns=%d artifacts=%d",
            initiative_id, session.id, len(turns), len(created_artifacts),
        )

        return Response({
            "session": SessionSerializer(session).data,
            "artifacts_created": len(created_artifacts),
            "rolling_summary_queued": True,
        }, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _load_json_from_request(request) -> list | dict:
    """Extract and decode JSON from multipart file upload or raw JSON body."""
    import json as _json

    file = request.FILES.get("file")
    if file:
        try:
            raw = file.read()
            return _json.loads(raw)
        except Exception as exc:
            raise ValueError(f"Could not parse uploaded file as JSON: {exc}") from exc

    # Raw JSON body (content_type application/json handled by DRF)
    if request.data and not isinstance(request.data, dict):
        return request.data  # already parsed by DRF parser

    # request.data is a dict — could be the JSON body itself if it passes DRF parsing
    if isinstance(request.data, (dict, list)):
        if request.data:
            return request.data

    # Last resort: re-parse request.body
    try:
        return _json.loads(request.body)
    except Exception as exc:
        raise ValueError("No JSON file or body found in request.") from exc


def _artifacts_to_distillation(artifact_specs: list[dict]) -> dict:
    """
    Derive a Session.distillation dict from the confirmed artifact list.
    The distillation drives the async rolling summary update.
    """
    decisions = []
    open_questions = []
    actions = []
    notes_parts = []

    for spec in artifact_specs:
        kind = spec.get("kind") or ""
        title = (spec.get("title") or "").strip()
        body = (spec.get("body") or "").strip()
        if not title:
            continue

        if kind == "decision":
            decisions.append(title)
        elif kind == "question":
            open_questions.append(title)
        elif kind == "action":
            actions.append(title)
        elif kind in ("annotation", "document"):
            notes_parts.append(body or title)

    return {
        "decisions": decisions,
        "open_questions": open_questions,
        "actions": actions,
        "notes": "\n\n".join(notes_parts),
    }


# ---------------------------------------------------------------------------
# ApertureLog views
# ---------------------------------------------------------------------------

def _get_initiative_for_aperture(request, initiative_id):
    """Return initiative if user is the sponsor (member ownership check)."""
    initiative = get_object_or_404(Initiative, pk=initiative_id)
    user_ct = ContentType.objects.get_for_model(request.user.__class__)
    is_owner = (
        initiative.sponsor_content_type_id == user_ct.id
        and str(initiative.sponsor_object_id) == str(request.user.id)
    )
    if not is_owner and not request.user.is_superuser:
        return None, Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return initiative, None


class ApertureLogView(APIView):
    """
    GET /api/initiatives/<id>/aperture-log
    Retrieve the full entry stream for an Initiative's ApertureLog.
    Ordered chronologically. Paginated (50/page).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, initiative_id):
        initiative, err = _get_initiative_for_aperture(request, initiative_id)
        if err:
            return err
        aperture_log = get_object_or_404(ApertureLog, initiative=initiative)
        page = int(request.query_params.get("page", 1))
        page_size = 50
        offset = (page - 1) * page_size
        entries = aperture_log.entries.all()[offset:offset + page_size]
        serializer = ApertureLogSerializer(aperture_log)
        data = serializer.data
        data["entries"] = ApertureLogEntrySerializer(entries, many=True).data
        return Response(data)


class ApertureLogEntryCreateView(APIView):
    """
    POST /api/initiatives/<id>/aperture-log/entries
    Create a new member-authored entry (prose, handoff, emph, seed_spawn).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, initiative_id):
        initiative, err = _get_initiative_for_aperture(request, initiative_id)
        if err:
            return err
        aperture_log = get_object_or_404(ApertureLog, initiative=initiative)
        serializer = ApertureLogEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            aperture_log=aperture_log,
            authored_by=request.user.username,
            created_by=request.user,
            is_system_generated=False,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ApertureLogEntryDetailView(APIView):
    """
    PATCH /api/initiatives/<id>/aperture-log/entries/<entry_id>
    Edit body or emph_note of a member-authored entry.
    Refused for ledger and seed_spawn entries.
    """
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, initiative_id, entry_id):
        initiative, err = _get_initiative_for_aperture(request, initiative_id)
        if err:
            return err
        aperture_log = get_object_or_404(ApertureLog, initiative=initiative)
        entry = get_object_or_404(ApertureLogEntry, pk=entry_id, aperture_log=aperture_log)
        if entry.kind in (ApertureLogEntryKind.LEDGER, ApertureLogEntryKind.SEED_SPAWN):
            return Response(
                {"detail": "System-generated entries cannot be edited."},
                status=status.HTTP_403_FORBIDDEN,
            )
        allowed_fields = {"body", "emph_note", "emph_accepted_to_summary"}
        data = {k: v for k, v in request.data.items() if k in allowed_fields}
        serializer = ApertureLogEntrySerializer(entry, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ApertureLogHandoffsView(APIView):
    """
    GET /api/initiatives/<id>/aperture-log/handoffs
    Return all handoff entries for this Initiative, ordered chronologically.
    Powers the handoff note sidebar.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, initiative_id):
        initiative, err = _get_initiative_for_aperture(request, initiative_id)
        if err:
            return err
        aperture_log = get_object_or_404(ApertureLog, initiative=initiative)
        entries = aperture_log.entries.filter(kind=ApertureLogEntryKind.HANDOFF)
        return Response(ApertureLogEntrySerializer(entries, many=True).data)


class ApertureOrientationView(APIView):
    """
    GET /api/members/me/aperture/orientation
    Return the member's 10 most recent contexts (Initiatives collapsed,
    standalones listed). Powers the WorkTable // orientation view.
    """
    permission_classes = [permissions.IsAuthenticated]

    _RECENCY_DAYS = 14
    _DEFAULT_LIMIT = 10

    def get(self, request):
        from django.utils import timezone as tz
        import datetime

        user = request.user
        user_ct = ContentType.objects.get_for_model(user.__class__)
        limit = int(request.query_params.get("limit", self._DEFAULT_LIMIT))

        # Initiatives sponsored by this user — sorted by most recently updated
        initiatives = (
            Initiative.objects.filter(
                sponsor_content_type=user_ct,
                sponsor_object_id=user.id,
            )
            .order_by("-updated_at")[:limit]
        )

        recency_cutoff = tz.now() - datetime.timedelta(days=self._RECENCY_DAYS)

        results = []
        for initiative in initiatives:
            last_handoff = None
            try:
                log = initiative.aperture_log
                last_handoff = (
                    log.entries.filter(kind=ApertureLogEntryKind.HANDOFF)
                    .order_by("-created_at")
                    .values_list("body", "created_at")
                    .first()
                )
            except ApertureLog.DoesNotExist:
                pass

            results.append({
                "type": "initiative",
                "id": str(initiative.id),
                "title": initiative.title,
                "status": initiative.status,
                "is_personal": initiative.is_personal,
                "updated_at": initiative.updated_at.isoformat() if initiative.updated_at else None,
                "last_handoff_body": last_handoff[0] if last_handoff else None,
                "last_handoff_at": last_handoff[1].isoformat() if last_handoff else None,
            })

        return Response({"contexts": results, "limit": limit})


class ApertureInitiativeTypeaheadView(APIView):
    """
    GET /api/members/me/aperture/initiatives?q=<query>&limit=10
    Initiative title prefix search for the // command typeahead.
    Returns the member's own Initiatives whose titles start with (or contain) q.
    """
    permission_classes = [permissions.IsAuthenticated]

    _DEFAULT_LIMIT = 10

    def get(self, request):
        user = request.user
        user_ct = ContentType.objects.get_for_model(user.__class__)
        q = request.query_params.get("q", "").strip()
        limit = min(int(request.query_params.get("limit", self._DEFAULT_LIMIT)), 20)

        qs = Initiative.objects.filter(
            sponsor_content_type=user_ct,
            sponsor_object_id=user.id,
        ).order_by("-updated_at")

        if q:
            qs = qs.filter(title__icontains=q)

        qs = qs[:limit]

        results = [
            {
                "id": str(initiative.id),
                "title": initiative.title,
                "status": initiative.status,
                "is_personal": initiative.is_personal,
                "updated_at": initiative.updated_at.isoformat() if initiative.updated_at else None,
            }
            for initiative in qs
        ]

        return Response({"initiatives": results})


# ============================================================================
# Mobile voice transcription (IM-7c)
# ============================================================================

class MobileTranscribeUploadView(APIView):
    """
    POST /api/initiatives/mobile/transcribe
    Accept a multipart audio upload, create a transcription job, queue Whisper.
    Returns {"job_id": "<uuid>"}.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser]

    def post(self, request):
        from initiatives.models import AgentTranscriptionJob
        from initiatives.tasks import transcribe_initiatives_job
        import uuid as _uuid

        audio_file = request.FILES.get("audio")
        if not audio_file:
            return Response({"detail": "audio file is required."}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile

        job_id = str(_uuid.uuid4())
        ext = audio_file.name.rsplit(".", 1)[-1] if "." in audio_file.name else "m4a"
        audio_path = f"initiatives/transcriptions/{job_id}.{ext}"
        default_storage.save(audio_path, ContentFile(audio_file.read()))

        job = AgentTranscriptionJob.objects.create(
            id=job_id,
            audio_path=audio_path,
            created_by=request.user,
        )

        transcribe_initiatives_job.delay(job_id)
        return Response({"job_id": str(job.id)}, status=status.HTTP_202_ACCEPTED)


class MobileTranscribeStatusView(APIView):
    """
    GET /api/initiatives/mobile/transcribe/<job_id>
    Return transcription job status and text when complete.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, job_id):
        from initiatives.models import AgentTranscriptionJob

        try:
            job = AgentTranscriptionJob.objects.get(id=job_id, created_by=request.user)
        except AgentTranscriptionJob.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "job_id": str(job.id),
            "status": job.status,
            "transcription_text": job.transcription_text or None,
            "failure_reason": job.failure_reason or None,
        })
