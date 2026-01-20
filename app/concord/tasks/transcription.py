# concord/tasks/transcription.py
"""
Celery tasks for audio transcription.

Tasks:
- transcribe_recording_task: Transcribe a recording and store results
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def transcribe_recording_task(
    self,
    recording_id: str,
    model_name: str = "base",
    language: Optional[str] = None,
    create_segments: bool = True,
    force: bool = False,
) -> dict:
    """
    Transcribe a recording and store the results.

    This task:
    1. Transitions recording status to 'transcribing'
    2. Runs Whisper transcription
    3. Creates Transcription and TranscriptSegment records
    4. Transitions recording status to 'ready' (or 'failed')

    Args:
        recording_id: Recording UUID
        model_name: Whisper model size (tiny, base, small, medium, large, large-v3)
        language: Language code (e.g., 'en'). Auto-detect if None.
        create_segments: Whether to create TranscriptSegment records
        force: Re-transcribe even if transcription exists (creates new version)

    Returns:
        Dict with results: {recording_id, transcription_id, status, segment_count}
    """
    from concord.models import (
        Recording,
        RecordingStatus,
        Transcription,
        TranscriptSegment,
    )
    from concord.services.whisper import transcribe_recording

    logger.info(f"[transcribe] Starting transcription for recording {recording_id}")

    try:
        # Get recording
        try:
            recording = Recording.objects.get(id=recording_id)
        except Recording.DoesNotExist:
            logger.error(f"[transcribe] Recording {recording_id} not found")
            return {"status": "error", "error": "Recording not found"}

        # Check if already processing or complete
        if recording.status == RecordingStatus.TRANSCRIBING:
            logger.info(f"[transcribe] Recording {recording_id} already transcribing, skipping")
            return {"status": "skipped", "reason": "already_transcribing"}

        if recording.status in [RecordingStatus.READY, RecordingStatus.ACCEPTED, RecordingStatus.PROMOTED]:
            # Check if we already have a transcription
            existing = Transcription.objects.filter(recording=recording).exists()
            if existing and not force:
                logger.info(f"[transcribe] Recording {recording_id} already has transcription, skipping (use force=True to re-transcribe)")
                return {"status": "skipped", "reason": "already_transcribed"}
            elif existing and force:
                logger.info(f"[transcribe] Recording {recording_id} has transcription but force=True, re-transcribing with {model_name}")

        # Transition to transcribing
        try:
            recording.transition_to(RecordingStatus.TRANSCRIBING)
            logger.info(f"[transcribe] Recording {recording_id} status -> transcribing")
        except ValueError as e:
            logger.warning(f"[transcribe] Could not transition to transcribing: {e}")
            # Continue anyway if we're in a state that allows transcription

        # Run transcription
        logger.info(f"[transcribe] Running Whisper ({model_name}) on recording {recording_id}")

        try:
            result = transcribe_recording(
                recording_id=recording_id,
                model_name=model_name,
                language=language,
            )
        except FileNotFoundError as e:
            logger.error(f"[transcribe] Audio file not found: {e}")
            _mark_recording_failed(recording, str(e))
            return {"status": "error", "error": str(e)}
        except ImportError as e:
            logger.error(f"[transcribe] Whisper not available: {e}")
            _mark_recording_failed(recording, f"Whisper not installed: {e}")
            return {"status": "error", "error": str(e)}

        logger.info(
            f"[transcribe] Transcription complete: {len(result.text)} chars, "
            f"{len(result.segments)} segments, language={result.language}"
        )

        # Store results
        with transaction.atomic():
            # Get next version number
            existing_versions = Transcription.objects.filter(
                recording=recording
            ).values_list('version', flat=True)
            next_version = max(existing_versions, default=0) + 1

            # Create Transcription
            transcription = Transcription.objects.create(
                recording=recording,
                version=next_version,
                text=result.text,
                language=result.language,
                confidence_avg=result.confidence_avg,
                whisper_model=result.model_name,
                processing_started_at=recording.processing_started_at,
                processing_completed_at=timezone.now(),
            )

            logger.info(f"[transcribe] Created Transcription {transcription.id} (v{next_version})")

            # Create TranscriptSegments
            segment_count = 0
            if create_segments and result.segments:
                segments_to_create = []
                for idx, seg in enumerate(result.segments):
                    segments_to_create.append(TranscriptSegment(
                        transcription=transcription,
                        segment_index=idx,
                        start_ms=seg.start_ms,
                        end_ms=seg.end_ms,
                        text=seg.text,
                        confidence=seg.confidence,
                        speaker_label=f"Speaker {seg.speaker_id}" if seg.speaker_id else "",
                    ))

                TranscriptSegment.objects.bulk_create(segments_to_create)
                segment_count = len(segments_to_create)
                logger.info(f"[transcribe] Created {segment_count} transcript segments")

            # Update recording duration if not set
            if not recording.duration_ms and result.duration_ms:
                recording.duration_ms = result.duration_ms
                recording.save(update_fields=['duration_ms'])

        # Transition to interpreting (next step)
        try:
            recording.transition_to(RecordingStatus.INTERPRETING)
            logger.info(f"[transcribe] Recording {recording_id} status -> interpreting")
        except ValueError as e:
            logger.warning(f"[transcribe] Could not transition to interpreting: {e}")

        # Queue interpretation task
        from concord.tasks.interpretation import interpret_recording_task
        interpret_recording_task.delay(recording_id=recording_id)
        logger.info(f"[transcribe] Queued interpretation task for recording {recording_id}")

        return {
            "status": "success",
            "recording_id": recording_id,
            "transcription_id": str(transcription.id),
            "version": next_version,
            "segment_count": segment_count,
            "language": result.language,
            "text_length": len(result.text),
        }

    except Exception as e:
        logger.error(f"[transcribe] Error transcribing {recording_id}: {e}", exc_info=True)

        # Mark recording as failed
        try:
            recording = Recording.objects.get(id=recording_id)
            _mark_recording_failed(recording, str(e))
        except Exception:
            pass

        # Retry with exponential backoff
        try:
            delay = 2 ** self.request.retries * 30  # 30s, 60s, 120s
            logger.info(f"[transcribe] Retrying in {delay}s (retry #{self.request.retries + 1})")
            raise self.retry(exc=e, countdown=delay)
        except MaxRetriesExceededError:
            logger.error(f"[transcribe] Max retries exceeded for recording {recording_id}")
            return {"status": "error", "error": f"Max retries exceeded: {e}"}


def _mark_recording_failed(recording, error_message: str):
    """Mark a recording as failed with error message."""
    from concord.models import RecordingStatus

    recording.status = RecordingStatus.FAILED
    recording.processing_error = error_message[:1000]  # Truncate if too long
    recording.processing_completed_at = timezone.now()
    recording.save(update_fields=['status', 'processing_error', 'processing_completed_at'])
    logger.info(f"[transcribe] Recording {recording.id} marked as failed")


@shared_task
def transcribe_pending_recordings(
    model_name: str = "base",
    limit: int = 5,
) -> dict:
    """
    Periodic task to transcribe recordings in 'uploaded' status.

    Finds recordings with audio that haven't been transcribed yet
    and queues them for transcription.

    Args:
        model_name: Whisper model to use
        limit: Maximum recordings to process per run

    Returns:
        Dict with stats: {queued_count, skipped_count}
    """
    from concord.models import Recording, RecordingStatus

    logger.info("[transcribe_pending] Looking for pending recordings")

    # Find recordings that are uploaded and have audio
    pending = Recording.objects.filter(
        status=RecordingStatus.UPLOADED,
    ).exclude(
        audio_path=""
    ).order_by('created_at')[:limit]

    queued_count = 0
    skipped_count = 0

    for recording in pending:
        # Check if already has transcription
        if recording.transcriptions.exists():
            logger.info(f"[transcribe_pending] Skipping {recording.id} - already has transcription")
            skipped_count += 1
            continue

        # Queue transcription
        transcribe_recording_task.delay(
            recording_id=str(recording.id),
            model_name=model_name,
        )
        queued_count += 1
        logger.info(f"[transcribe_pending] Queued transcription for {recording.id}")

    logger.info(f"[transcribe_pending] Complete: queued={queued_count}, skipped={skipped_count}")

    return {
        "queued_count": queued_count,
        "skipped_count": skipped_count,
    }
