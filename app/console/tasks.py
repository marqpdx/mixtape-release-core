import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from concord.services.whisper import transcribe_audio
from console.models import HubCapture, HubCaptureStatus

_DEFAULT_TENANT_ID = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
_DEFAULT_TENANT_NAMESPACE = getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads")

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
    from initiatives.models import ActionRun, ActionRunExecutionMode, ActionRunInitiatorType, ActionRunStatus

    try:
        capture = HubCapture.objects.select_related("audio_file", "group", "owner").get(id=capture_id)
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

    action_run = ActionRun.objects.create(
        tool_name="console.transcribe",
        status=ActionRunStatus.RUNNING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        tenant_id=_DEFAULT_TENANT_ID,
        tenant_namespace=_DEFAULT_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id=str(capture.owner_id),
        request_payload={"capture_id": capture_id, "kind": capture.kind},
        started_at=timezone.now(),
    )

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

        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.result_payload = {"captures_created": len(items), "transcript_length": len(transcript)}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "result_payload", "completed_at", "updated_at"])
        return {"status": "ok", "captures_created": len(items)}

    except Exception as exc:
        logger.error("[console] Transcription failed for %s: %s", capture_id, exc, exc_info=True)
        action_run.status = ActionRunStatus.FAILED
        action_run.error_payload = {"error": str(exc), "capture_id": capture_id}
        action_run.completed_at = timezone.now()
        action_run.save(update_fields=["status", "error_payload", "completed_at", "updated_at"])
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        capture.status = HubCaptureStatus.FAILED
        capture.transcript_error = str(exc)
        capture.save(update_fields=["status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": str(exc)}


@shared_task(queue="catalyst")
def register_inbox_keeper_task() -> None:
    """Celery beat heartbeat keeping InboxKeeper's registration alive (K-7) —
    same rationale as RecencyKeeper's heartbeat (K-5): Clio's routing can
    only reach an already-registered Keeper, and InboxKeeper isn't spawned
    per-request."""
    from console.inbox_keeper import ensure_inbox_keeper_registered
    ensure_inbox_keeper_registered()


@shared_task(queue="catalyst")
def answer_inbox_type_guess(keeper_id: str, intent: str, question_params: dict) -> dict:
    """AD-11 answer_task for InboxKeeper's question shape. question_params
    must carry capture_id."""
    from console.inbox_keeper import guess_capture_type

    capture_id = question_params.get("capture_id")
    if not capture_id:
        return {
            "intent": intent, "keeper_id": keeper_id,
            "answer": {"error": "capture_id is required"}, "confidence": None,
        }
    try:
        capture = HubCapture.objects.get(id=capture_id)
    except HubCapture.DoesNotExist:
        return {
            "intent": intent, "keeper_id": keeper_id,
            "answer": {"error": "capture not found"}, "confidence": None,
        }
    guess = guess_capture_type(capture.body)
    return {
        "intent": intent,
        "keeper_id": keeper_id,
        "answer": {"guessed_type": guess["guessed_type"], "capture_id": capture_id},
        "confidence": guess["confidence"],
    }
