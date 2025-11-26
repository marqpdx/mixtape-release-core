# chat/services.py

import re
from django.contrib.contenttypes.models import ContentType
from .models import ChatMessage, MessageMention
from activity.models import Action

class ChatMessageService:
    @staticmethod
    def create_message_with_mentions(conversation, sender, text):
        """Create a message and handle mentions/notifications"""
        # Create the message first
        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=sender,
            text=text
        )

        # Parse and create mentions
        mentions = ChatMessageService.parse_and_create_mentions(message, text)

        # Create mention notifications
        ChatMessageService.create_mention_notifications(message, mentions)

        return message

    @staticmethod
    def parse_and_create_mentions(message, text):
        """Extract mentions from text and create MessageMention objects"""
        mentions = []

        # Regex to find @mentions (simple version)
        mention_pattern = r'@(\w+(?:-\w+)*)'  # Handles @username or @group-name
        mention_matches = re.finditer(mention_pattern, text)

        for match in mention_matches:
            mention_text = match.group(0)  # Full "@username"
            username_or_slug = match.group(1)  # Just "username"

            # Try to find user first
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(username=username_or_slug)

                mention = MessageMention.objects.create(
                    message=message,
                    mentionee_content_type=ContentType.objects.get_for_model(User),
                    mentionee_object_id=str(user.id),
                    mention_text=mention_text
                )
                mentions.append(mention)
                continue

            except User.DoesNotExist:
                pass

            # Try to find group
            try:
                from groups.models import Group  # Adjust import path
                group = Group.objects.get(slug=username_or_slug)

                mention = MessageMention.objects.create(
                    message=message,
                    mentionee_content_type=ContentType.objects.get_for_model(Group),
                    mentionee_object_id=str(group.id),
                    mention_text=mention_text
                )
                mentions.append(mention)

            except Group.DoesNotExist:
                pass  # Mention not found, skip

        return mentions

    @staticmethod
    def create_mention_notifications(message, mentions):
        """Create Activity notifications for mentions"""
        for mention in mentions:
            Action.objects.create(
                actor_content_type=ContentType.objects.get_for_model(message.sender),
                actor_id=str(message.sender.id),
                actor_label="user",
                object_content_type=ContentType.objects.get_for_model(message),
                object_id=str(message.id),
                context_content_type=ContentType.objects.get_for_model(message.conversation),
                context_id=str(message.conversation.id),
                verb="mentioned",
                activity_code="chat.mention.created",
                priority="critical",
                dedupe_key=f"mention-{message.id}-{mention.mentionee_content_type.id}-{mention.mentionee_object_id}",
                audience={
                    "type": "mention_targets",
                    "mentionee_type": mention.mentionee_content_type.model,
                    "mentionee_id": mention.mentionee_object_id
                }
            )