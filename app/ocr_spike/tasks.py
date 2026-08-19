from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction

from inkwell.client import InkwellUnavailableError

logger = logging.getLogger(__name__)


def _configured_local_engines() -> list[str]:
    raw = getattr(settings, "OCR_SPIKE_LOCAL_ENGINES", "tesseract,paddleocr")
    engines = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return engines or ["tesseract"]


def _save_attempt_result(attempt, result: dict) -> None:
    attempt.engine_name = result.get("engine_name", attempt.engine_name or "")
    attempt.raw_text = result.get("text", "")
    attempt.raw_result_json = result.get("raw_result_json", result)
    attempt.confidence_summary = result.get("confidence_summary", {})
    attempt.processing_time_ms = result.get("processing_time_ms")
    attempt.status = attempt.__class__.Status.COMPLETE
    attempt.save(update_fields=[
        "engine_name",
        "raw_text",
        "raw_result_json",
        "confidence_summary",
        "processing_time_ms",
        "status",
        "updated_at",
    ])


@shared_task(name="ocr_spike.tasks.run_local_ocr_for_artifact", bind=True, max_retries=2, default_retry_delay=20)
def run_local_ocr_for_artifact(self, artifact_id: str) -> dict:
    from .models import OcrSpikeArtifact, OcrSpikePage, OcrSpikeRecognitionAttempt
    from .services import prepare_artifact_pages, recognize_page_with_inkwell

    try:
        artifact = OcrSpikeArtifact.objects.get(pk=artifact_id)
    except OcrSpikeArtifact.DoesNotExist:
        logger.error("[ocr_spike] artifact %s not found", artifact_id)
        return {"status": "error", "error": "artifact_not_found"}

    artifact.status = OcrSpikeArtifact.Status.PREPARING
    artifact.error_message = ""
    artifact.save(update_fields=["status", "error_message", "updated_at"])

    try:
        prepared_pages = prepare_artifact_pages(artifact)
        with transaction.atomic():
            artifact.pages.all().delete()
            pages = [
                OcrSpikePage.objects.create(
                    artifact=artifact,
                    page_number=prepared.page_number,
                    image_path=prepared.image_path,
                    width=prepared.width,
                    height=prepared.height,
                    preparation_status=OcrSpikePage.PreparationStatus.READY,
                )
                for prepared in prepared_pages
            ]
            artifact.page_count = len(pages)
            artifact.status = OcrSpikeArtifact.Status.RECOGNIZING
            artifact.save(update_fields=["page_count", "status", "updated_at"])

        for page in pages:
            for engine in _configured_local_engines():
                attempt = OcrSpikeRecognitionAttempt.objects.create(
                    page=page,
                    provider=OcrSpikeRecognitionAttempt.Provider.LOCAL,
                    engine_name=engine,
                    status=OcrSpikeRecognitionAttempt.Status.PROCESSING,
                )
                try:
                    result = recognize_page_with_inkwell(page, provider="local", engine=engine)
                except InkwellUnavailableError as exc:
                    attempt.status = OcrSpikeRecognitionAttempt.Status.FAILED
                    attempt.error_message = str(exc)
                    attempt.save(update_fields=["status", "error_message", "updated_at"])
                    continue

                _save_attempt_result(attempt, result)

        artifact.status = OcrSpikeArtifact.Status.READY_FOR_REVIEW
        artifact.save(update_fields=["status", "updated_at"])
        return {"status": "success", "artifact_id": artifact_id, "page_count": artifact.page_count}
    except Exception as exc:
        artifact.status = OcrSpikeArtifact.Status.FAILED
        artifact.error_message = str(exc)
        artifact.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("[ocr_spike] local OCR failed for artifact %s", artifact_id)
        raise


@shared_task(name="ocr_spike.tasks.run_cloud_ocr_for_page", bind=True, max_retries=1, default_retry_delay=20)
def run_cloud_ocr_for_page(self, page_id: str) -> dict:
    from .models import OcrSpikeArtifact, OcrSpikePage, OcrSpikeRecognitionAttempt
    from .services import recognize_page_with_inkwell

    try:
        page = OcrSpikePage.objects.select_related("artifact").get(pk=page_id)
    except OcrSpikePage.DoesNotExist:
        logger.error("[ocr_spike] page %s not found", page_id)
        return {"status": "error", "error": "page_not_found"}

    if page.artifact.privacy_sensitivity == OcrSpikeArtifact.PrivacySensitivity.COMPLETE:
        logger.warning("[ocr_spike] blocked cloud OCR for complete-privacy artifact %s", page.artifact_id)
        return {"status": "blocked", "reason": "privacy_sensitivity_complete"}

    attempt = OcrSpikeRecognitionAttempt.objects.create(
        page=page,
        provider=OcrSpikeRecognitionAttempt.Provider.CLOUD,
        status=OcrSpikeRecognitionAttempt.Status.PROCESSING,
    )
    try:
        result = recognize_page_with_inkwell(page, provider="cloud")
    except InkwellUnavailableError as exc:
        attempt.status = OcrSpikeRecognitionAttempt.Status.FAILED
        attempt.error_message = str(exc)
        attempt.save(update_fields=["status", "error_message", "updated_at"])
        return {"status": "error", "error": str(exc)}

    _save_attempt_result(attempt, result)
    return {"status": "success", "page_id": page_id, "attempt_id": str(attempt.id)}
