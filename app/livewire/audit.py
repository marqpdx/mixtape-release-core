from chat.models import Conversation, ConversationAuditEvent


def log(conversation: Conversation, event_type: str, actor=None, **metadata) -> ConversationAuditEvent:
    return ConversationAuditEvent.objects.create(
        conversation=conversation,
        event_type=event_type,
        actor=actor,
        metadata=metadata,
    )


# Convenience shorthands — call these from services/signals, never pass raw text.

def conversation_created(conversation: Conversation, actor) -> ConversationAuditEvent:
    return log(conversation, ConversationAuditEvent.EventType.CONVERSATION_CREATED, actor=actor)


def participant_joined(conversation: Conversation, actor, joined_user_id) -> ConversationAuditEvent:
    return log(conversation, ConversationAuditEvent.EventType.PARTICIPANT_JOINED, actor=actor,
               joined_user_id=str(joined_user_id))


def participant_left(conversation: Conversation, actor, left_user_id) -> ConversationAuditEvent:
    return log(conversation, ConversationAuditEvent.EventType.PARTICIPANT_LEFT, actor=actor,
               left_user_id=str(left_user_id))


def message_sent(conversation: Conversation, actor) -> ConversationAuditEvent:
    return log(conversation, ConversationAuditEvent.EventType.MESSAGE_SENT, actor=actor)
