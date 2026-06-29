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


def _min_referenced_key_version(messages_qs) -> int | None:
    """Returns the lowest key_version still referenced by any message in the queryset."""
    min_version = None
    for msg in messages_qs:
        if msg.message_type == "voice":
            v = msg.audio_key_version or 1
        else:
            # M1 (LW-D3): prefer the server-recorded version (set at write time, clamped to
            # max known bundle version). Fall back to text parsing only for legacy messages
            # written before message_key_version existed.
            if msg.message_key_version is not None:
                v = msg.message_key_version
            elif msg.text and msg.text.startswith("e2e:"):
                parts = msg.text.split(":", 2)
                try:
                    v = int(parts[1]) if len(parts) >= 2 else 1
                except ValueError:
                    v = 1
            else:
                continue
        if min_version is None or v < min_version:
            min_version = v
    return min_version


@shared_task(
    name="chat.tasks.enforce_retention_policies",
    queue="default",
)
def enforce_retention_policies():
    """
    Phase B — deletes messages older than the conversation's retention period.
    LW-D2 — also prunes ConversationKeyBundle rows for Ephemeral conversations
    whose key_version is no longer referenced by any remaining message.
    """
    from datetime import timedelta
    from chat.models import ChatMessage, ConversationKeyBundle, ConversationRetentionPolicy, TrustProfile

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
    pruned_bundle_total = 0

    for policy in due:
        delta = PERIOD_MAP.get(policy.retention_period)
        if not delta:
            continue
        conversation = policy.conversation
        cutoff = timezone.now() - delta
        # H4: collect audio file references before deleting messages —
        # audio_file uses SET_NULL on delete, leaving StoredFile and the
        # underlying object-storage file orphaned without this step.
        expiring_audio_file_ids = list(
            ChatMessage.objects.filter(
                conversation=conversation,
                created_at__lt=cutoff,
                audio_file__isnull=False,
            ).values_list("audio_file_id", flat=True)
        )

        count, _ = ChatMessage.objects.filter(
            conversation=conversation,
            created_at__lt=cutoff,
        ).delete()
        deleted_total += count

        if expiring_audio_file_ids:
            from django.core.files.storage import default_storage
            from files.models import StoredFile
            for sf in StoredFile.objects.filter(id__in=expiring_audio_file_ids):
                try:
                    default_storage.delete(sf.file_path)
                except Exception as exc:
                    logger.warning(
                        "[livewire/retention] Failed to delete audio file %s: %s", sf.file_path, exc
                    )
            StoredFile.objects.filter(id__in=expiring_audio_file_ids).delete()

        if count:
            logger.info(
                "[livewire/retention] Deleted %d messages from conversation %s (policy: %s)",
                count,
                policy.conversation_id,
                policy.retention_period,
            )

        # LW-D2: key-bundle pruning — Ephemeral only. Server never holds plaintext keys;
        # deleting bundles for expired key versions removes the server-side wrapping
        # material, so a future key compromise cannot decrypt messages already deleted.
        if conversation.trust_profile != TrustProfile.EPHEMERAL:
            continue

        remaining_qs = ChatMessage.objects.filter(conversation=conversation).only(
            "text", "audio_key_version", "audio_iv", "message_key_version", "message_type"
        )
        if not remaining_qs.exists():
            pruned, _ = ConversationKeyBundle.objects.filter(conversation=conversation).delete()
        else:
            min_version = _min_referenced_key_version(remaining_qs)
            if min_version is not None and min_version > 1:
                pruned, _ = ConversationKeyBundle.objects.filter(
                    conversation=conversation,
                    key_version__lt=min_version,
                ).delete()
            else:
                pruned = 0

        if pruned:
            pruned_bundle_total += pruned
            logger.info(
                "[livewire/keys] Pruned %d key bundles from conversation %s",
                pruned,
                conversation.id,
            )

    logger.info(
        "[livewire/retention] Enforcement complete — %d messages deleted, %d key bundles pruned.",
        deleted_total,
        pruned_bundle_total,
    )
    return {"deleted": deleted_total, "bundles_pruned": pruned_bundle_total}
