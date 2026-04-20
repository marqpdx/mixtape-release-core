from django.utils import timezone
from django.utils.text import slugify
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    BusinessProspect,
    ProspectInsight,
    ProspectIntakeSession,
    ProspectNote,
    ProspectQuestion,
    ProspectResponse,
)
from ..signals import intake_submitted
from .serializers import (
    BusinessProspectSerializer,
    ProspectInsightSerializer,
    ProspectIntakeSessionInternalSerializer,
    ProspectIntakeSessionSerializer,
    ProspectNoteSerializer,
    ProspectResponseSerializer,
)


def _get_session_by_token(token):
    try:
        return ProspectIntakeSession.objects.select_related("prospect").get(resume_token=token)
    except ProspectIntakeSession.DoesNotExist:
        return None


# ============================================================================
# Public intake API (token-gated, no auth)
# ============================================================================

class IntakeSessionDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        session = _get_session_by_token(token)
        if session is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if session.token_expires_at and session.token_expires_at < timezone.now():
            return Response({"detail": "This link has expired."}, status=status.HTTP_410_GONE)
        return Response(ProspectIntakeSessionSerializer(session).data)


class IntakeResponseSaveView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        session = _get_session_by_token(token)
        if session is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if session.token_expires_at and session.token_expires_at < timezone.now():
            return Response({"detail": "This link has expired."}, status=status.HTTP_410_GONE)
        if session.status == "submitted":
            return Response({"detail": "Session already submitted."}, status=status.HTTP_400_BAD_REQUEST)

        question_id = request.data.get("question_id")
        response_text = request.data.get("response_text", "")

        try:
            question = ProspectQuestion.objects.get(id=question_id)
        except ProspectQuestion.DoesNotExist:
            return Response({"detail": "Question not found."}, status=status.HTTP_404_NOT_FOUND)

        response, created = ProspectResponse.objects.update_or_create(
            intake_session=session,
            question=question,
            defaults={
                "question_prompt_snapshot": question.prompt,
                "response_text": response_text,
                "response_mode": "typed",
            },
        )

        if session.status == "draft":
            session.status = "in_progress"
            session.started_at = timezone.now()
            session.save(update_fields=["status", "started_at"])

        return Response(ProspectResponseSerializer(response).data, status=status.HTTP_200_OK)


class IntakeSubmitView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        session = _get_session_by_token(token)
        if session is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if session.token_expires_at and session.token_expires_at < timezone.now():
            return Response({"detail": "This link has expired."}, status=status.HTTP_410_GONE)
        if session.status == "submitted":
            return Response({"detail": "Already submitted."}, status=status.HTTP_400_BAD_REQUEST)

        active_questions = ProspectQuestion.objects.filter(is_active=True)
        answered_ids = set(
            ProspectResponse.objects.filter(
                intake_session=session,
                response_text__gt="",
            ).values_list("question_id", flat=True)
        )
        unanswered = [str(q.id) for q in active_questions if q.id not in answered_ids]
        if unanswered:
            return Response(
                {"detail": "All questions must be answered.", "unanswered_question_ids": unanswered},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session.status = "submitted"
        session.submitted_at = timezone.now()
        session.save(update_fields=["status", "submitted_at"])

        intake_submitted.send(sender=ProspectIntakeSession, intake_session=session)

        return Response({"detail": "Submitted successfully."})


# ============================================================================
# Internal staff API (IsAdminUser)
# ============================================================================

class ProspectListCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        prospects = BusinessProspect.objects.all().order_by("-created_at")
        return Response(BusinessProspectSerializer(prospects, many=True).data)

    def post(self, request):
        serializer = BusinessProspectSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        name = serializer.validated_data["name"]
        slug = slugify(name)
        base_slug = slug
        counter = 1
        while BusinessProspect.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        prospect = serializer.save(slug=slug)
        return Response(BusinessProspectSerializer(prospect).data, status=status.HTTP_201_CREATED)


class ProspectDetailView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def _get(self, slug):
        try:
            return BusinessProspect.objects.get(slug=slug)
        except BusinessProspect.DoesNotExist:
            return None

    def get(self, request, slug):
        prospect = self._get(slug)
        if prospect is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(BusinessProspectSerializer(prospect).data)

    def patch(self, request, slug):
        prospect = self._get(slug)
        if prospect is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = BusinessProspectSerializer(prospect, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)


class IntakeSessionCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, slug):
        try:
            prospect = BusinessProspect.objects.get(slug=slug)
        except BusinessProspect.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        session = ProspectIntakeSession.objects.create(
            prospect=prospect,
            mode=request.data.get("mode", "pre_meeting"),
            created_by=request.user,
            meeting_date=request.data.get("meeting_date"),
        )
        intake_url = request.build_absolute_uri(f"/intake/{session.resume_token}/")
        data = ProspectIntakeSessionInternalSerializer(session).data
        data["intake_url"] = intake_url
        return Response(data, status=status.HTTP_201_CREATED)


class IntakeSessionDetailInternalView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request, slug, session_id):
        try:
            session = ProspectIntakeSession.objects.prefetch_related("responses__question").get(
                id=session_id, prospect__slug=slug
            )
        except ProspectIntakeSession.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ProspectIntakeSessionInternalSerializer(session).data)


class ResponseRefinementView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def patch(self, request, slug, session_id, response_id):
        try:
            response = ProspectResponse.objects.get(
                id=response_id, intake_session__id=session_id, intake_session__prospect__slug=slug
            )
        except ProspectResponse.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        response.human_refined_text = request.data.get("human_refined_text", response.human_refined_text)
        response.save(update_fields=["human_refined_text", "updated_at"])
        return Response(ProspectResponseSerializer(response).data)


class InsightCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, slug, session_id):
        try:
            prospect = BusinessProspect.objects.get(slug=slug)
            session = ProspectIntakeSession.objects.get(id=session_id, prospect=prospect)
        except (BusinessProspect.DoesNotExist, ProspectIntakeSession.DoesNotExist):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ProspectInsightSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        insight = serializer.save(prospect=prospect, session=session, source="human", created_by=request.user)
        return Response(ProspectInsightSerializer(insight).data, status=status.HTTP_201_CREATED)


class NoteCreateView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request, slug):
        try:
            prospect = BusinessProspect.objects.get(slug=slug)
        except BusinessProspect.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ProspectNoteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        note = serializer.save(prospect=prospect, created_by=request.user)
        return Response(ProspectNoteSerializer(note).data, status=status.HTTP_201_CREATED)
