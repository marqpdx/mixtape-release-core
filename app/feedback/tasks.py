from __future__ import annotations

import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_feedback_voice_task(self, stored_file_id: str, username: str | None = None):
    """
    Transcribe a feedback voice upload via the shared Whisper pipeline.
    On completion emits feedback:voice_transcribed to the user's Livewire room.
    Stores transcript text on the linked FeedbackItem (if already submitted)
    or holds it on the StoredFile for retrieval while the popover is still open.
    """
    from concord.services.whisper import transcribe_audio
    from files.models import StoredFile

    try:
        stored_file = StoredFile.objects.get(id=stored_file_id)
    except StoredFile.DoesNotExist:
        logger.error("[feedback] StoredFile %s not found for transcription", stored_file_id)
        return {"status": "missing"}

    if not stored_file.file_path:
        logger.error("[feedback] StoredFile %s has no file_path", stored_file_id)
        return {"status": "failed", "reason": "no_file_path"}

    try:
        result = transcribe_audio(stored_file.file_path)
        transcript = (result.text or "").strip()
    except Exception as exc:
        logger.error("[feedback] Transcription failed for %s: %s", stored_file_id, exc, exc_info=True)
        raise self.retry(exc=exc)

    # Propagate transcript to any FeedbackItem already linked to this voice file
    from feedback.models import FeedbackItem
    FeedbackItem.objects.filter(voice_file_id=stored_file_id, voice_transcript="").update(
        voice_transcript=transcript
    )

    # Notify the user's socket so the Beacon popover can show the transcript
    if username:
        _notify_voice_transcribed(stored_file_id=stored_file_id, username=username, transcript=transcript)

    return {"status": "ok", "chars": len(transcript), "stored_file_id": stored_file_id}


def _notify_voice_transcribed(stored_file_id: str, username: str, transcript: str) -> None:
    livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
    secret = getattr(settings, "LIVEWIRE_NOTIFY_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Notify-Secret"] = secret
    try:
        requests.post(
            f"{livewire_url}/notify",
            json={
                "event": "feedback:voice_transcribed",
                "username": username,
                "payload": {"voice_upload_id": stored_file_id, "transcript": transcript},
            },
            headers=headers,
            timeout=3,
        )
    except Exception as exc:
        logger.warning("[feedback] Failed to notify livewire of voice transcription: %s", exc)
