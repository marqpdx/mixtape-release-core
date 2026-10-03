# folio/tasks.py
#
# Folio Notes PoC — background transcription for voice FolioNotes. Mirrors
# writing.tasks.transcribe_seed_task: persist first (the view already saved
# the audio and the note), transcribe second, push a Livewire event so the
# mobile list-refetch + socket pattern from Notebook ports over unchanged.

import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from concord.services.whisper import transcribe_audio
from folio.models import FolioNote, FolioNoteSource, FolioNoteStatus

logger = logging.getLogger(__name__)


def _notify_folio_note_transcribed(note: FolioNote) -> None:
    """Push folio_note:transcribed to the owner's socket via Livewire /notify. Fire-and-forget."""
    if not note.created_by:
        return
    livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
    secret = getattr(settings, "LIVEWIRE_NOTIFY_SECRET", "")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Notify-Secret"] = secret
    try:
        requests.post(
            f"{livewire_url}/notify",
            json={
                "event": "folio_note:transcribed",
                "username": note.created_by.username,
                "payload": {"folio_note_id": str(note.id), "folio_id": str(note.folio_id)},
            },
            headers=headers,
            timeout=3,
        )
    except Exception as exc:
        logger.warning("[folio-notes] Failed to notify livewire of transcription: %s", exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_folio_note_task(self, note_id: str):
    try:
        note = FolioNote.objects.select_related("created_by", "audio_file").get(id=note_id)
    except FolioNote.DoesNotExist:
        logger.error("[folio-notes] FolioNote %s not found", note_id)
        return {"status": "missing"}

    if note.source_type != FolioNoteSource.VOICE:
        return {"status": "skipped", "reason": "not_voice"}

    if not note.audio_file or not note.audio_file.file_path:
        note.status = FolioNoteStatus.FAILED
        note.transcript_error = "Missing audio file."
        note.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        result = transcribe_audio(note.audio_file.file_path)
        note.transcript_text = (result.text or "").strip()
        note.transcript_model = result.model_name or ""
        note.transcript_backend = result.backend or ""
        note.transcript_created_at = timezone.now()
        note.transcript_error = ""
        note.status = FolioNoteStatus.READY
        note.save(update_fields=[
            "transcript_text",
            "transcript_model",
            "transcript_backend",
            "transcript_created_at",
            "transcript_error",
            "status",
            "updated_at",
        ])
        _notify_folio_note_transcribed(note)
        return {"status": "ok", "chars": len(note.transcript_text)}
    except Exception as exc:
        # The audio stays on the note — a failed transcription is a
        # recoverable note, never a lost capture (build plan §41).
        logger.error("[folio-notes] Transcription failed for %s: %s", note_id, exc, exc_info=True)
        note.status = FolioNoteStatus.FAILED
        note.transcript_error = str(exc)
        note.save(update_fields=["status", "transcript_error", "updated_at"])
        raise self.retry(exc=exc)
