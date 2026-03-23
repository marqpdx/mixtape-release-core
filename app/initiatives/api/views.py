# initiatives/api/views.py

import logging

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from groups.models import Group
from initiatives.models import (
    Artifact,
    ArtifactKind,
    DistillationState,
    Initiative,
    InitiativeStatus,
    LinkedOutput,
    QualityScanState,
    Session,
)
from initiatives.api.serializers import (
    ArtifactSerializer,
    DistillationCurateSerializer,
    InitiativeSerializer,
    LinkedOutputSerializer,
    RollingSummaryUpdateSerializer,
    SessionSerializer,
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

    def get(self, request, group_slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def post(self, request, group_slug):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def get(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return Response(InitiativeSerializer(initiative).data)

    def patch(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(group_slug)
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

    def delete(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        group = _get_group(group_slug)
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

    def patch(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def _get_initiative(self, group_slug, initiative_id):
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)
        sessions = initiative.sessions.all()
        return Response(SessionSerializer(sessions, many=True).data)

    def post(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)

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


class SessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, group_slug, initiative_id, session_id):
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return get_object_or_404(Session, id=session_id, initiative=initiative)

    def get(self, request, group_slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        session = self._get_session(group_slug, initiative_id, session_id)
        return Response(SessionSerializer(session).data)

    def patch(self, request, group_slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        session = self._get_session(group_slug, initiative_id, session_id)

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

    def post(self, request, group_slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        message = request.data.get("message", "").strip()
        if not message:
            return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)

        group = _get_group(group_slug)
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


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------

class ProposeDistillationView(APIView):
    """
    POST to trigger AI distillation proposal for a closed session.
    Full implementation in AI integration pass.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, group_slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def post(self, request, group_slug, initiative_id, session_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def _get_initiative(self, group_slug, initiative_id):
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)
        artifacts = initiative.artifacts.all()
        kind_filter = request.query_params.get("kind")
        if kind_filter:
            artifacts = artifacts.filter(kind=kind_filter)
        return Response(ArtifactSerializer(artifacts, many=True).data)

    def post(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)

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

    def _get_artifact(self, group_slug, initiative_id, artifact_id):
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        initiative = get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )
        return get_object_or_404(Artifact, id=artifact_id, initiative=initiative)

    def patch(self, request, group_slug, initiative_id, artifact_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        artifact = self._get_artifact(group_slug, initiative_id, artifact_id)
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

    def post(self, request, group_slug, initiative_id, artifact_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group = _get_group(group_slug)
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

    def _get_initiative(self, group_slug, initiative_id):
        group = _get_group(group_slug)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(group)
        return get_object_or_404(
            Initiative,
            id=initiative_id,
            sponsor_content_type=ct,
            sponsor_object_id=group.pk,
        )

    def get(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)
        outputs = initiative.linked_outputs.all()
        return Response(LinkedOutputSerializer(outputs, many=True).data)

    def post(self, request, group_slug, initiative_id):
        if not _superuser_required(request):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        initiative = self._get_initiative(group_slug, initiative_id)

        serializer = LinkedOutputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        output = serializer.save(initiative=initiative)
        return Response(LinkedOutputSerializer(output).data, status=status.HTTP_201_CREATED)
