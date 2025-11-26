# chat/api/serializers.py

import logging
from rest_framework import serializers
from django.contrib.auth import get_user_model
from chat.models import Conversation, ConversationParticipant, ChatMessage, ConversationStatusTracker, MessageMention, MessageReaction

logger = logging.getLogger(__name__)
User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Minimal user serializer for chat context"""
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name"]


class BaseConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "slug", "title", "created_at"]


class ConversationSerializer(BaseConversationSerializer):
    participants = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=True
    )

    slug = serializers.CharField(read_only=True)  # Add this

    class Meta(BaseConversationSerializer.Meta):
        fields = BaseConversationSerializer.Meta.fields + ["participants"]

    def create(self, validated_data):
        participants_usernames = validated_data.pop("participants")
        logger.debug(f"Creating conversation with participants: {participants_usernames}")
        current_user = self.context["request"].user
        logger.debug(f"Current user: {current_user.username}")

        # Ensure current user is included
        all_usernames = sorted(set(participants_usernames + [current_user.username]))
        logger.debug(f"All usernames (including current user): {all_usernames}")

        participants = list(User.objects.filter(username__in=all_usernames))
        logger.debug(f"Participants fetched: {[u.username for u in participants]}")

        if len(participants) != len(all_usernames):
            found = {u.username for u in participants}
            missing = set(all_usernames) - found
            raise serializers.ValidationError(
                {"participants": f"User(s) not found: {', '.join(missing)}"}
            )

        # Try to find an existing direct conversation
        if len(participants) == 2:
            logger.debug("Checking for existing 1:1 conversation...")
            conversations = Conversation.objects.filter(
                participants__user=participants[0]
            ).distinct()

            for convo in conversations:
                convo_users = set(p.user.username for p in convo.participants.all())
                if convo_users == set(all_usernames):
                    logger.info(f"Reusing existing conversation: {convo.slug}")
                    return convo

        # No existing found — create a new one
        conversation = Conversation.objects.create(
            created_by=current_user,
            **validated_data
        )
        for user in participants:
            ConversationParticipant.objects.create(user=user, conversation=conversation)

        logger.info(f"Created new conversation: {conversation.slug}")
        return conversation


class ConversationReadSerializer(BaseConversationSerializer):
    participants = serializers.SerializerMethodField()  # ✅ override participant logic

    class Meta(BaseConversationSerializer.Meta):
        fields = BaseConversationSerializer.Meta.fields + ["participants"]

    def get_participants(self, obj):
            # ✅ Returns list of usernames, or you could return full user dicts
            return [p.user.username for p in obj.participants.all()]



class MessageReactionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = MessageReaction
        fields = ["id", "reaction_name", "user", "created_at"]

class MessageMentionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageMention
        fields = ["id", "mention_text", "mentionee_content_type", "mentionee_object_id"]




class ChatMessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    mentions = MessageMentionSerializer(many=True, read_only=True)

    reaction_summary = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ["id", "text", "created_at", "sender", "reactions", "mentions", "reaction_summary"]
        read_only_fields = ['sender', 'created_at', 'reactions', 'mentions']

    def get_reaction_summary(self, obj):
        """Return reaction_name counts grouped by reaction_name type"""
        from django.db.models import Count
        summary = obj.reactions.values('reaction_name').annotate(
            count=Count('reaction_name')
        ).order_by('-count')

        return [
            {
                'reaction_name': item['reaction_name'],
                'count': item['count'],
                'users': list(obj.reactions.filter(reaction_name=item['reaction_name']).values_list('user__username', flat=True))
            }
            for item in summary
        ]

    def create(self, validated_data):
        # Your existing create method with mentions...
        conversation = self.context.get('conversation')

        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=validated_data['sender'],
            text=validated_data['text']
        )

        self._create_mentions(message)
        return message

    def _create_mentions(self, message):
        """Parse mentions from message text and create notifications"""
        import re
        from django.contrib.contenttypes.models import ContentType
        from django.contrib.auth import get_user_model
        from ..models import MessageMention
        # from activity.models import Action

        # Find @mentions in text
        mention_pattern = r'@(\w+(?:-\w+)*)'
        mention_matches = re.finditer(mention_pattern, message.text)

        User = get_user_model()

        for match in mention_matches:
            mention_text = match.group(0)  # "@username"
            username_or_slug = match.group(1)  # "username"

            # Try to find user first
            try:
                user = User.objects.get(username=username_or_slug)
                mention = MessageMention.objects.create(
                    message=message,
                    mentionee_content_type=ContentType.objects.get_for_model(User),
                    mentionee_object_id=str(user.id),
                    mention_text=mention_text
                )
                self._create_mention_notification(message, mention)
                continue
            except User.DoesNotExist:
                pass

            # Try to find group (add your Group model import)
            # try:
            #     group = Group.objects.get(slug=username_or_slug)
            #     mention = MessageMention.objects.create(...)
            #     self._create_mention_notification(message, mention)
            # except Group.DoesNotExist:
            #     pass

    def _create_mention_notification(self, message, mention):
        """Create Activity notification for mention using proper producer"""
        from django.contrib.auth import get_user_model
        from activity.producers_chat import on_chat_mention

        User = get_user_model()

        # Resolve the mentioned user from the mention
        try:
            mentioned_user = User.objects.get(pk=mention.mentionee_object_id)
        except User.DoesNotExist:
            # If user doesn't exist (e.g., group mention), skip notification
            # TODO: Handle group mentions when groups app is integrated
            return

        # Use the proper producer function which handles:
        # - Creating Action with all required fields
        # - Creating ActionOutbox for fanout
        # - Enqueuing Celery task for notification delivery
        on_chat_mention(
            message=message,
            conversation=message.conversation,
            mentioned_users=[mentioned_user]
        )


class ConversationStatusTrackerSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversationStatusTracker
        fields = ["is_muted", "last_viewed_at"]


