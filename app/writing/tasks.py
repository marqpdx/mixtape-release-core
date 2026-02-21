import logging
from django.utils import timezone
from celery import shared_task

from concord.services.whisper import transcribe_audio
from writing.models import Seed

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def transcribe_seed_task(self, seed_id: str):
    """
    Background transcription for voice seeds.
    """
    try:
        seed = Seed.objects.get(id=seed_id)
    except Seed.DoesNotExist:
        logger.error("[seeds] Seed %s not found", seed_id)
        return {"status": "missing"}

    if seed.kind != "voice":
        return {"status": "skipped", "reason": "not_voice"}

    if not seed.audio_file or not seed.audio_file.file_path:
        seed.status = "failed"
        seed.transcript_error = "Missing audio file."
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        seed.status = "processing"
        seed.save(update_fields=["status", "updated_at"])

        result = transcribe_audio(seed.audio_file.file_path)
        transcript = (result.text or "").strip()

        seed.transcript_text = transcript
        seed.body_text = transcript
        seed.status = "ready"
        seed.transcript_provider = "whisper"
        seed.transcript_created_at = timezone.now()
        seed.transcript_error = ""
        seed.save(update_fields=[
            "transcript_text",
            "body_text",
            "status",
            "transcript_provider",
            "transcript_created_at",
            "transcript_error",
            "updated_at",
        ])
        return {"status": "ok", "chars": len(transcript)}
    except Exception as exc:
        logger.error("[seeds] Transcription failed for %s: %s", seed_id, exc, exc_info=True)
        seed.status = "failed"
        seed.transcript_error = str(exc)
        seed.save(update_fields=["status", "transcript_error", "updated_at"])
        raise self.retry(exc=exc)
