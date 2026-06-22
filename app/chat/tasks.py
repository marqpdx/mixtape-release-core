# chat/tasks.py

import logging
import os
from django.utils import timezone
from celery import shared_task

from concord.services.whisper import transcribe_audio

logger = logging.getLogger(__name__)

socket_q = os.getenv("SHARED_RABBIT_CHAT_QUEUE", "mixtape_shared_rabbit_chat_queue")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="transcription",
)
def transcribe_chat_message_task(self, message_id: str):
    """
    Background transcription for voice chat messages.
    Reuses the same whisper.cpp pipeline as seed transcription.
    After completion, emits 'transcript_ready' to the conversation room via RabbitMQ.
    """
    from chat.models import ChatMessage

    try:
        message = ChatMessage.objects.select_related("audio_file", "conversation").get(
            id=message_id
        )
    except ChatMessage.DoesNotExist:
        logger.error("[chat] ChatMessage %s not found for transcription", message_id)
        return {"status": "missing"}

    if message.message_type != "voice":
        return {"status": "skipped", "reason": "not_voice"}

    if not message.audio_file or not message.audio_file.file_path:
        message.transcript_status = "failed"
        message.transcript_error = "Missing audio file."
        message.save(update_fields=["transcript_status", "transcript_error", "updated_at"])
        return {"status": "failed", "reason": "missing_audio"}

    try:
        result = transcribe_audio(message.audio_file.file_path)
        transcript = (result.text or "").strip()

        message.transcript_text = transcript
        message.transcript_status = "done"
        message.transcript_provider = result.backend or "whisper"
        message.transcript_model = result.model_name
        message.transcript_backend = result.backend
        message.transcript_created_at = timezone.now()
        message.transcript_error = ""
        message.save(update_fields=[
            "transcript_text",
            "transcript_status",
            "transcript_provider",
            "transcript_model",
            "transcript_backend",
            "transcript_created_at",
            "transcript_error",
            "updated_at",
        ])

        # Emit transcript_ready to the conversation room via RabbitMQ → Livewire
        _emit_transcript_ready(message)

        return {"status": "ok", "chars": len(transcript)}

    except Exception as exc:
        logger.error(
            "[chat] Transcription failed for message %s: %s", message_id, exc, exc_info=True
        )
        message.transcript_status = "failed"
        message.transcript_error = str(exc)
        message.save(update_fields=["transcript_status", "transcript_error", "updated_at"])
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    name="chat.tasks.emit_transcript_ready_task",
    queue=socket_q,
)
def emit_transcript_ready_task(self, event_data: dict):
    """
    Publishes transcript_ready event to the RabbitMQ chat queue.
    Consumed by Livewire which broadcasts to the conversation room.
    """
    try:
        logger.info(
            "[chat] Publishing transcript_ready for message %s in conversation %s",
            event_data.get("message_id"),
            event_data.get("conversation_slug"),
        )
        return {"status": "published"}
    except Exception as exc:
        logger.error("[chat] Failed to publish transcript_ready: %s", exc)
        raise self.retry(exc=exc)


def _emit_transcript_ready(message):
    """Convenience wrapper — queues the transcript_ready socket event."""
    event_data = {
        "event": "transcript_ready",
        "conversation_slug": message.conversation.slug,
        "message_id": str(message.id),
        "transcript": message.transcript_text or "",
    }
    emit_transcript_ready_task.delay(event_data)


@shared_task(
    name="chat.tasks.enforce_retention_policies",
    queue="default",
)
def enforce_retention_policies():
    """
    Phase B — deletes messages older than the conversation's retention period.
    Runs on all Conversations with enforcement_enabled=True and a non-indefinite policy.
    Ephemeral conversations always have enforcement_enabled=True (enforced at creation).
    """
    from datetime import timedelta
    from django.utils import timezone
    from chat.models import ChatMessage, ConversationRetentionPolicy

    PERIOD_MAP = {
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
    }

    due = ConversationRetentionPolicy.objects.filter(
        enforcement_enabled=True,
    ).exclude(retention_period="indefinite").select_related("conversation")

    deleted_total = 0
    for policy in due:
        delta = PERIOD_MAP.get(policy.retention_period)
        if not delta:
            continue
        cutoff = timezone.now() - delta
        count, _ = ChatMessage.objects.filter(
            conversation=policy.conversation,
            created_at__lt=cutoff,
        ).delete()
        deleted_total += count
        if count:
            logger.info(
                "[livewire/retention] Deleted %d messages from conversation %s (policy: %s)",
                count,
                policy.conversation_id,
                policy.retention_period,
            )

    logger.info("[livewire/retention] Enforcement complete — %d messages deleted.", deleted_total)
    return {"deleted": deleted_total}
