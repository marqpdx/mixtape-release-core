from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def transcribe_capture(self, capture_id: str) -> dict:
    """
    MC-5: Transcribe a MediaCapture via Whisper.

    Pulls the media_file path from MediaCapture, sends it through
    transcribe_audio(), creates a Transcript row, and updates
    MediaCapture.status → READY (or FAILED).  Chains to
    ingest_to_stackroom on success.
    """
    from concord.services.whisper import transcribe_audio
    from .models import CaptureStatus, MediaCapture, Transcript

    logger.info("[transcribe_capture] Starting for capture %s", capture_id)

    try:
        capture = MediaCapture.objects.get(id=capture_id)
    except MediaCapture.DoesNotExist:
        logger.error("[transcribe_capture] Capture %s not found", capture_id)
        return {"status": "error", "error": "Capture not found"}

    if capture.status == CaptureStatus.TRANSCRIBING:
        logger.info("[transcribe_capture] Already transcribing %s, skipping", capture_id)
        return {"status": "skipped", "reason": "already_transcribing"}

    capture.status = CaptureStatus.TRANSCRIBING
    capture.save(update_fields=["status", "updated_at"])

    try:
        result = transcribe_audio(
            audio_path=capture.media_file,
            model_name="base",
        )
    except (FileNotFoundError, ImportError) as exc:
        logger.error("[transcribe_capture] %s — %s", capture_id, exc)
        capture.status = CaptureStatus.FAILED
        capture.save(update_fields=["status", "updated_at"])
        return {"status": "error", "error": str(exc)}
    except Exception as exc:
        logger.error("[transcribe_capture] Unexpected error for %s: %s", capture_id, exc, exc_info=True)
        capture.status = CaptureStatus.FAILED
        capture.save(update_fields=["status", "updated_at"])
        try:
            delay = 2 ** self.request.retries * 30
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            return {"status": "error", "error": f"Max retries exceeded: {exc}"}

    segments = [
        {
            "start_s": seg.start_ms / 1000,
            "end_s": seg.end_ms / 1000,
            "text": seg.text,
            "speaker": seg.speaker_id,
        }
        for seg in result.segments
    ]

    with transaction.atomic():
        transcript = Transcript.objects.create(
            capture=capture,
            body_json=segments,
            raw_text=result.text,
            model_used=f"{result.backend}:{result.model_name}",
        )

        if result.duration_ms and not capture.duration_seconds:
            capture.duration_seconds = result.duration_ms // 1000

        capture.transcript = transcript
        capture.status = CaptureStatus.READY
        capture.save(update_fields=["transcript", "status", "duration_seconds", "updated_at"])

    logger.info(
        "[transcribe_capture] Done for %s — transcript %s, %d segments",
        capture_id, transcript.id, len(segments),
    )

    ingest_to_stackroom.apply_async(
        kwargs={"transcript_id": str(transcript.id)},
        queue="commons",
    )

    return {
        "status": "success",
        "capture_id": capture_id,
        "transcript_id": str(transcript.id),
        "segment_count": len(segments),
        "language": result.language,
    }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_to_stackroom(self, transcript_id: str) -> dict:
    """
    MC-6: Push Transcript text into Stackroom.

    Uses the TranscriptAdapter registered in inkwell.stackroom_adapters.
    Sets Transcript.stackroom_ingested_at on success.
    """
    from inkwell.stackroom_integration_service import ingest_object
    from .models import Transcript

    logger.info("[ingest_to_stackroom] Starting for transcript %s", transcript_id)

    try:
        transcript = Transcript.objects.select_related("capture__author").get(id=transcript_id)
    except Transcript.DoesNotExist:
        logger.error("[ingest_to_stackroom] Transcript %s not found", transcript_id)
        return {"status": "error", "error": "Transcript not found"}

    try:
        ingest_object(transcript, reason="media_capture")
    except Exception as exc:
        logger.error("[ingest_to_stackroom] Failed for %s: %s", transcript_id, exc, exc_info=True)
        try:
            delay = 2 ** self.request.retries * 60
            raise self.retry(exc=exc, countdown=delay)
        except MaxRetriesExceededError:
            return {"status": "error", "error": f"Max retries exceeded: {exc}"}

    transcript.stackroom_ingested_at = timezone.now()
    transcript.save(update_fields=["stackroom_ingested_at"])

    logger.info("[ingest_to_stackroom] Done for transcript %s", transcript_id)
    return {"status": "success", "transcript_id": transcript_id}
