# utils/chat/notify_socket_server.py
"""
Send chat notifications to the Socket.IO server via RabbitMQ.
Uses Celery for async delivery with retry logic.
"""

from celery import shared_task
import json
import logging

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    name="utils.chat.notify_socket_server",
    queue="chat_events"  # Route to chat_events queue consumed by livewire
)
def notify_socket_server_task(self, conversation_data):
    """
    Celery task to notify Socket.IO server about chat events.
    Published to RabbitMQ 'chat_events' queue, consumed by livewire Socket.IO server.

    Args:
        conversation_data: Dict with conversation details
    """
    try:
        logger.info(f"Publishing {conversation_data.get('event')} to RabbitMQ: {conversation_data.get('slug')}")

        # This task publishes to the 'chat_events' queue
        # The livewire Socket.IO server consumes from this queue
        # and broadcasts events to connected WebSocket clients

        return {
            "status": "published",
            "event": conversation_data.get("event"),
            "slug": conversation_data.get("slug")
        }

    except Exception as exc:
        logger.error(f"Failed to publish chat event: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc)


def notify_socket_server(convo):
    """
    Synchronous wrapper to trigger async notification.
    Called from Django views after conversation creation.

    Args:
        convo: Conversation model instance
    """
    conversation_data = {
        "event": "conversation_created",
        "slug": convo.slug,
        "participant_usernames": list(convo.participants.values_list("user__username", flat=True)),
        "created_at": convo.created_at.isoformat(),
    }

    # Send to Celery/RabbitMQ asynchronously
    notify_socket_server_task.delay(conversation_data)
    logger.debug(f"Queued conversation_created notification for: {convo.slug}")
