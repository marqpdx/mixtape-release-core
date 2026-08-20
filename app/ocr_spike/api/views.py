from __future__ import annotations

import mimetypes
import logging

from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils.text import get_valid_filename
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ocr_spike.models import (
    OcrSpikeArtifact,
    OcrSpikeEvaluation,
    OcrSpikeFeedbackNote,
    OcrSpikePage,
    OcrSpikeRecognitionAttempt,
    OcrSpikeShapingAttempt,
)
from ocr_spike.shapes import RECIPE_SHAPE_ID, RECIPE_SHAPE_VERSION, list_available_shapes
from ocr_spike.tasks import run_cloud_ocr_for_page, run_local_ocr_for_artifact, run_recipe_shape_for_page
from mixtape.celery_app import app as celery_app

from .serializers import (
    OcrSpikeArtifactSerializer,
    OcrSpikeEvaluationSerializer,
    OcrSpikeEvaluationWriteSerializer,
    OcrSpikeFeedbackWriteSerializer,
    OcrSpikeShapeRunSerializer,
    OcrSpikePageSerializer,
)

logger = logging.getLogger(__name__)


class OcrSpikeArtifactListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        artifacts = OcrSpikeArtifact.objects.filter(created_by=request.user).order_by("-created_at")
        return Response(OcrSpikeArtifactSerializer(artifacts, many=True).data)

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)

        privacy = request.data.get("privacy_sensitivity") or OcrSpikeArtifact.PrivacySensitivity.MEDIUM
        if privacy not in OcrSpikeArtifact.PrivacySensitivity.values:
            return Response({"detail": "privacy_sensitivity must be low, medium, or complete."}, status=400)

        artifact = OcrSpikeArtifact.objects.create(
            original_filename=upload.name or "artifact",
            source_file_path="",
            content_type=upload.content_type or mimetypes.guess_type(upload.name or "")[0] or "",
            file_size=getattr(upload, "size", 0) or 0,
            privacy_sensitivity=privacy,
            created_by=request.user,
        )

        safe_name = get_valid_filename(upload.name or "artifact")
        source_path = f"ocr_spike/{artifact.id}/{safe_name}"
        saved_path = default_storage.save(source_path, upload)
        artifact.source_file_path = saved_path
        artifact.save(update_fields=["source_file_path", "updated_at"])

        return Response(OcrSpikeArtifactSerializer(artifact).data, status=status.HTTP_201_CREATED)


class OcrSpikeArtifactDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, artifact_id):
        artifact = _get_owned_artifact(request.user, artifact_id)
        if not artifact:
            return Response({"detail": "Not found."}, status=404)
        return Response(OcrSpikeArtifactSerializer(artifact).data)


class OcrSpikeArtifactRunLocalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, artifact_id):
        artifact = _get_owned_artifact(request.user, artifact_id)
        if not artifact:
            return Response({"detail": "Not found."}, status=404)
        async_result = run_local_ocr_for_artifact.apply_async(args=[str(artifact.id)], queue="ocr")
        logger.warning(
            "[ocr_spike] queued local OCR artifact_id=%s task_id=%s broker=%s queue=ocr",
            artifact.id,
            async_result.id,
            celery_app.conf.broker_url,
        )
        artifact.status = OcrSpikeArtifact.Status.PREPARING
        artifact.save(update_fields=["status", "updated_at"])
        data = dict(OcrSpikeArtifactSerializer(artifact).data)
        data["queued_task_id"] = async_result.id
        return Response(data, status=202)


class OcrSpikeArtifactPagesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, artifact_id):
        artifact = _get_owned_artifact(request.user, artifact_id)
        if not artifact:
            return Response({"detail": "Not found."}, status=404)
        pages = artifact.pages.prefetch_related("attempts", "shaping_attempts").select_related("evaluation").all()
        return Response({"pages": OcrSpikePageSerializer(pages, many=True, context={"request": request}).data})


class OcrSpikeShapesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"shapes": list_available_shapes()})


class OcrSpikePageFileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, page_id):
        page = _get_owned_page(request.user, page_id)
        if not page:
            return Response({"detail": "Not found."}, status=404)
        path = page.image_path or page.artifact.source_file_path
        if not path or not default_storage.exists(path):
            return Response({"detail": "File not found."}, status=404)
        content_type = page.artifact.content_type or mimetypes.guess_type(page.artifact.original_filename)[0] or "application/octet-stream"
        return FileResponse(default_storage.open(path, "rb"), content_type=content_type)


class OcrSpikePageCloudRecognizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, page_id):
        page = _get_owned_page(request.user, page_id)
        if not page:
            return Response({"detail": "Not found."}, status=404)
        if page.artifact.privacy_sensitivity == OcrSpikeArtifact.PrivacySensitivity.COMPLETE:
            return Response(
                {"detail": "Cloud escalation is disabled for this artifact because privacy sensitivity is complete."},
                status=403,
            )
        async_result = run_cloud_ocr_for_page.apply_async(args=[str(page.id)], queue="ocr")
        logger.warning(
            "[ocr_spike] queued cloud OCR page_id=%s task_id=%s broker=%s queue=ocr",
            page.id,
            async_result.id,
            celery_app.conf.broker_url,
        )
        return Response({"page_id": str(page.id), "status": "processing", "queued_task_id": async_result.id}, status=202)


class OcrSpikePageEvaluationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, page_id):
        page = _get_owned_page(request.user, page_id)
        if not page:
            return Response({"detail": "Not found."}, status=404)

        serializer = OcrSpikeEvaluationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        selected_attempt = None
        selected_attempt_id = data.get("selected_attempt_id")
        if selected_attempt_id:
            selected_attempt = OcrSpikeRecognitionAttempt.objects.filter(id=selected_attempt_id, page=page).first()
            if not selected_attempt:
                return Response({"detail": "selected_attempt_id is not valid for this page."}, status=400)

        evaluation, _ = OcrSpikeEvaluation.objects.update_or_create(
            page=page,
            defaults={
                "selected_attempt": selected_attempt,
                "final_text": data.get("final_text", ""),
                "outcome": data["outcome"],
                "quality_rating": data.get("quality_rating"),
                "correction_effort": data.get("correction_effort", ""),
                "search_summary": data.get("search_summary", ""),
                "notes": data.get("notes", ""),
            },
        )

        artifact = page.artifact
        if artifact.pages.count() == artifact.pages.filter(evaluation__isnull=False).count():
            artifact.status = OcrSpikeArtifact.Status.COMPLETE
            artifact.save(update_fields=["status", "updated_at"])

        return Response(OcrSpikeEvaluationSerializer(evaluation).data)


class OcrSpikePageRecipeShapeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, page_id):
        page = _get_owned_page(request.user, page_id)
        if not page:
            return Response({"detail": "Not found."}, status=404)

        serializer = OcrSpikeShapeRunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        shape_id = data.get("shape_id") or RECIPE_SHAPE_ID
        if shape_id != RECIPE_SHAPE_ID:
            return Response({"detail": f"Unsupported shape_id for this spike: {shape_id}"}, status=400)

        selected_attempt_id = data.get("selected_attempt_id")
        if selected_attempt_id:
            exists = OcrSpikeRecognitionAttempt.objects.filter(id=selected_attempt_id, page=page).exists()
            if not exists:
                return Response({"detail": "selected_attempt_id is not valid for this page."}, status=400)

        shaping_attempt = OcrSpikeShapingAttempt.objects.create(
            page=page,
            selected_attempt=OcrSpikeRecognitionAttempt.objects.filter(id=selected_attempt_id, page=page).first() if selected_attempt_id else None,
            shape_id=RECIPE_SHAPE_ID,
            shape_version=RECIPE_SHAPE_VERSION,
            input_text=data.get("reviewed_text", ""),
            status=OcrSpikeShapingAttempt.Status.PROCESSING,
        )
        async_result = run_recipe_shape_for_page.apply_async(
            args=[
                str(page.id),
                str(selected_attempt_id) if selected_attempt_id else None,
                data.get("reviewed_text", ""),
                str(shaping_attempt.id),
            ],
            queue="ocr",
        )
        logger.warning(
            "[ocr_spike] queued recipe shaping page_id=%s task_id=%s broker=%s queue=ocr",
            page.id,
            async_result.id,
            celery_app.conf.broker_url,
        )
        return Response({
            "page_id": str(page.id),
            "shaping_attempt_id": str(shaping_attempt.id),
            "shape_id": shape_id,
            "status": "processing",
            "queued_task_id": async_result.id,
        }, status=202)


class OcrSpikeFeedbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OcrSpikeFeedbackWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        artifact = None
        if data.get("artifact_id"):
            artifact = _get_owned_artifact(request.user, data["artifact_id"])
            if not artifact:
                return Response({"detail": "artifact_id is not valid."}, status=400)

        page = None
        if data.get("page_id"):
            page = _get_owned_page(request.user, data["page_id"])
            if not page:
                return Response({"detail": "page_id is not valid."}, status=400)
            if artifact and page.artifact_id != artifact.id:
                return Response({"detail": "page_id does not belong to artifact_id."}, status=400)

        note = OcrSpikeFeedbackNote.objects.create(
            artifact=artifact,
            page=page,
            screen=data["screen"],
            note=data["note"],
            created_by=request.user,
        )
        return Response({"feedback_note_id": str(note.id), "created_at": note.created_at.isoformat()}, status=201)


def _get_owned_artifact(user, artifact_id):
    return OcrSpikeArtifact.objects.filter(id=artifact_id, created_by=user).first()


def _get_owned_page(user, page_id):
    return OcrSpikePage.objects.select_related("artifact").filter(id=page_id, artifact__created_by=user).first()
