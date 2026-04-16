# concord/tasks/interpretation.py
"""
Celery tasks for transcription interpretation.

Tasks:
- interpret_recording_task: Interpret a transcription and transition to ready
"""

from __future__ import annotations

import logging
from typing import Optional

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=15)
def interpret_recording_task(
    self,
    recording_id: str,
    use_llm: bool = False,  # Default to extractive; inkwell will handle LLM later
) -> dict:
    """
    Interpret a recording's transcription and transition to ready.

    This task:
    1. Gets the latest transcription for the recording
    2. Generates a summary (LLM or extractive)
    3. Stores summary on the Recording
    4. Transitions recording status to 'ready'

    Args:
        recording_id: Recording UUID
        use_llm: Whether to attempt LLM-based summarization

    Returns:
        Dict with results: {recording_id, status, summary_length, method}
    """
    from concord.models import Recording, RecordingStatus
    from concord.services.interpretation import interpret_recording

    logger.info(f"[interpret] Starting interpretation for recording {recording_id}")

    try:
        # Get recording
        try:
            recording = Recording.objects.get(id=recording_id)
        except Recording.DoesNotExist:
            logger.error(f"[interpret] Recording {recording_id} not found")
            return {"status": "error", "error": "Recording not found"}

        # Check status
        if recording.status != RecordingStatus.INTERPRETING:
            logger.info(
                f"[interpret] Recording {recording_id} not in interpreting status "
                f"(current: {recording.status}), skipping"
            )
            return {"status": "skipped", "reason": f"status is {recording.status}"}

        # Check if has transcription
        if not recording.transcriptions.exists():
            logger.error(f"[interpret] Recording {recording_id} has no transcription")
            _mark_recording_failed(recording, "No transcription available for interpretation")
            return {"status": "error", "error": "No transcription"}

        # Run interpretation
        logger.info(f"[interpret] Running interpretation for recording {recording_id}")

        try:
            result = interpret_recording(recording_id, use_llm=use_llm)
        except Exception as e:
            logger.warning(f"[interpret] Interpretation failed, using fallback: {e}")
            # Don't fail the whole task, just skip summarization
            result = None

        # Store summary on recording
        if result and result.summary:
            recording.summary = result.summary
            recording.save(update_fields=['summary'])
            logger.info(
                f"[interpret] Stored summary ({len(result.summary)} chars) "
                f"using {result.method} method"
            )

        # Transition to ready
        try:
            recording.transition_to(RecordingStatus.READY)
            logger.info(f"[interpret] Recording {recording_id} status -> ready")
        except ValueError as e:
            logger.warning(f"[interpret] Could not transition to ready: {e}")
            # Force update status if transition fails
            recording.status = RecordingStatus.READY
            recording.processing_completed_at = timezone.now()
            recording.save(update_fields=['status', 'processing_completed_at'])

        from stackroom.integration.service import enqueue_ingest_object
        transaction.on_commit(lambda: enqueue_ingest_object(recording, reason="transcription_ready"))

        return {
            "status": "success",
            "recording_id": recording_id,
            "summary_length": len(result.summary) if result else 0,
            "key_points_count": len(result.key_points) if result else 0,
            "method": result.method if result else "none",
            "word_count": result.word_count if result else 0,
        }

    except Exception as e:
        logger.error(f"[interpret] Error interpreting {recording_id}: {e}", exc_info=True)

        # Try to mark as ready anyway (don't block on interpretation failure)
        try:
            recording = Recording.objects.get(id=recording_id)
            recording.status = RecordingStatus.READY
            recording.processing_completed_at = timezone.now()
            recording.save(update_fields=['status', 'processing_completed_at'])
            logger.info(f"[interpret] Recording {recording_id} marked ready despite interpretation error")
            return {
                "status": "success_with_error",
                "recording_id": recording_id,
                "error": str(e),
            }
        except Exception:
            pass

        # Retry if marking ready also failed
        try:
            delay = 2 ** self.request.retries * 15
            logger.info(f"[interpret] Retrying in {delay}s (retry #{self.request.retries + 1})")
            raise self.retry(exc=e, countdown=delay)
        except MaxRetriesExceededError:
            logger.error(f"[interpret] Max retries exceeded for recording {recording_id}")
            return {"status": "error", "error": f"Max retries exceeded: {e}"}


def _mark_recording_failed(recording, error_message: str):
    """Mark a recording as failed with error message."""
    from concord.models import RecordingStatus

    recording.status = RecordingStatus.FAILED
    recording.processing_error = error_message[:1000]
    recording.processing_completed_at = timezone.now()
    recording.save(update_fields=['status', 'processing_error', 'processing_completed_at'])
    logger.info(f"[interpret] Recording {recording.id} marked as failed")
