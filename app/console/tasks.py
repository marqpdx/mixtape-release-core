import logging

from celery import shared_task
from django.db import transaction

from concord.services.whisper import transcribe_audio
from console.models import HubCapture, HubCaptureStatus

logger = logging.getLogger(__name__)

LIST_PARSE_KINDS = {"need_more", "fix"}
MAX_WORD_THRESHOLD = 8


def _parse_capture_list(text: str) -> list[str]:
    import re

    parts = re.split(r"[,;]\s*|\n+", text)
    parts = [re.sub(r"^\d+[.)]\s*", "", p.strip()) for p in parts]
    parts = [re.sub(r"^[-•*]\s*", "", p).strip() for p in parts if p.strip()]

    if len(parts) <= 1:
        return [text.strip()] if text.strip() else []

    avg_words = sum(len(p.split()) for p in parts) / len(parts)
    return parts if avg_words <= MAX_WORD_THRESHOLD else [text.strip()]


@shared_task(bind=True, max_retries=3, default_retry_delay=10, queue="transcription")
def transcribe_hub_capture_task(self, capture_id: str):
    try:
        capture = HubCapture.objects.select_related("audio_file", "group").get(id=capture_id)
    except HubCapture.DoesNotExist:
        logger.error("[console] HubCapture %s not found", capture_id)
        return {"status": "missing"}

    if capture.status != HubCaptureStatus.PROCESSING:
        return {"status": "skipped", "reason": f"status={capture.status}"}

    if not capture.audio_file or not capture.audio_file.file_path:
        capture.status = HubCaptureStatus.FAILED
        capture.transcript_error = "Missing audio file."
        capture.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        result = transcribe_audio(capture.audio_file.file_path)
        transcript = (result.text or "").strip()
        if not transcript:
            raise RuntimeError("Transcription returned empty text")

        items = (
            _parse_capture_list(transcript)
            if capture.kind in LIST_PARSE_KINDS
            else [transcript]
        )
        if not items:
            raise RuntimeError("No capture items parsed from transcript")

        with transaction.atomic():
            capture.body = items[0]
            capture.status = HubCaptureStatus.OPEN
            capture.transcript_error = ""
            capture.save(update_fields=["body", "status", "transcript_error", "updated_at"])

            extra_items = items[1:]
            if extra_items:
                HubCapture.objects.bulk_create(
                    [
                        HubCapture(
                            owner=capture.owner,
                            kind=capture.kind,
                            body=item,
                            visibility=capture.visibility,
                            status=HubCaptureStatus.OPEN,
                            group=capture.group,
                        )
                        for item in extra_items
                    ]
                )

        return {"status": "ok", "captures_created": len(items)}
    except Exception as exc:
        logger.error("[console] Transcription failed for %s: %s", capture_id, exc, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        capture.status = HubCaptureStatus.FAILED
        capture.transcript_error = str(exc)
        capture.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": str(exc)}
