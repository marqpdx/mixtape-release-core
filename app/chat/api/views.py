# chat/api/views.py

from .serializers import ChatMessageSerializer
from django.db.models import Count
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from livewire.auth import ServiceJWTAuthentication  # your class that verifies SERVICE_JWT_SECRET
from livewire.permissions import HasChatWriteScope  # checks "chat:write" in request.auth_payload
from rest_framework import generics, permissions
from rest_framework import status
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, NotAuthenticated
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.api.serializers import BaseConversationSerializer, ConversationSerializer, ConversationReadSerializer, ChatMessageSerializer, ConversationStatusTrackerSerializer, MessageReactionSerializer
from chat.models import Conversation, ConversationParticipant, ChatMessage, ConversationStatusTracker, MessageReaction, MessageMention
from chat.permissions import IsConversationParticipant
from chat.utils import generate_conversation_title
from users.models import CustomUser
# from utils.activity import format_chat_message_log, log_activity
from utils.chat.notify_socket_server import notify_socket_server


class MessagePagination(PageNumberPagination):
    """Pagination for chat messages"""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def conversation_list_create(request):
    user = request.user

    if request.method == "GET":
        conversations = Conversation.objects.filter(participants__user=user).distinct()
        serializer = ConversationReadSerializer(conversations, many=True)
        return Response(serializer.data)

    if request.method == "POST":
        participants_data = request.data.get("participants", [])

        if not participants_data or not isinstance(participants_data, list):
            return Response({"error": "participants must be a list of usernames"}, status=400)

        usernames = list(set(participants_data + [user.username]))  # Include the sender

        # Generate default title if none provided
        title = request.data.get("title")
        if not title:
            title = generate_conversation_title(usernames, user)

        # Add title to the request data
        conversation_data = request.data.copy()
        conversation_data["title"] = title

        # 1-on-1 conversation logic
        if len(usernames) == 2:
            users = CustomUser.objects.filter(username__in=usernames)
            if users.count() == 2:
                existing = (
                    Conversation.objects
                    .annotate(num_participants=Count("participants"))
                    .filter(num_participants=2, participants__user__in=users)
                    .distinct()
                )

                for convo in existing:
                    convo_users = convo.participants.values_list("user__username", flat=True)
                    if set(convo_users) == set(usernames):
                        return Response(ConversationReadSerializer(convo).data, status=status.HTTP_200_OK)

        # Otherwise, create new
        serializer = ConversationSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            conversation = serializer.save()
            notify_socket_server(conversation)

            return Response(ConversationReadSerializer(conversation).data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversation_detail(request, slug):
    user = request.user
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(user=user, conversation=conversation).exists():
        return Response({"detail": "Not a participant of this conversation."}, status=status.HTTP_403_FORBIDDEN)

    serializer = ConversationReadSerializer(conversation)
    return Response(serializer.data)





@api_view(["GET", "POST"])
@authentication_classes([ServiceJWTAuthentication, JWTAuthentication])
@permission_classes([IsAuthenticated])  # must be authenticated for either method
def conversation_messages(request, slug):
    user = request.user
    conversation = get_object_or_404(Conversation, slug=slug)

    # Must be a participant for any access
    is_participant = ConversationParticipant.objects.filter(
        user=user, conversation=conversation
    ).exists()
    if not is_participant:
        return Response(
            {"detail": "Not a participant of this conversation."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "GET":
        messages = ChatMessage.objects.filter(
            conversation=conversation
        ).select_related('sender').prefetch_related('reactions__user', 'mentions').order_by("created_at")

        # Apply pagination
        paginator = MessagePagination()
        paginated_messages = paginator.paginate_queryset(messages, request)
        serializer = ChatMessageSerializer(paginated_messages, many=True)
        return paginator.get_paginated_response(serializer.data)

    # ---- POST: service-token only, bound to the conversation ----
    # Ensure the successful authenticator is the ServiceJWTAuthentication
    if not isinstance(getattr(request, "successful_authenticator", None), ServiceJWTAuthentication):
        return Response(
            {"detail": "Service token required for writes."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Check scope "chat:write"
    if not HasChatWriteScope().has_permission(request, None):
        return Response(
            {"detail": "Missing chat:write scope."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Enforce conversation binding: token 'conv' must match URL slug
    auth_payload = getattr(request, "auth_payload", {}) or {}
    token_conv = auth_payload.get("conv")
    if token_conv and token_conv != slug:
        return Response(
            {"detail": "Token conversation mismatch."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Proceed to create message
    serializer = ChatMessageSerializer(data=request.data, context={"conversation": conversation})
    if serializer.is_valid():
        message = serializer.save(sender=user, conversation=conversation)

        # (optional) notify other participants, enqueue events, etc.
        # participants = ConversationParticipant.objects.filter(conversation=conversation).exclude(user=user)
        # for participant in participants:
        #     ...

        return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_conversations(request):
    user = request.user
    query = request.GET.get("q", "").strip()

    if not query:
        return Response([])

    user_conversations = Conversation.objects.filter(participants__user=user).distinct()

    # Basic name match against any participants
    filtered = user_conversations.filter(
        Q(participants__user__first_name__icontains=query) |
        Q(participants__user__last_name__icontains=query) |
        Q(participants__user__username__icontains=query)
    ).distinct()

    serializer = BaseConversationSerializer(filtered, many=True)
    return Response(serializer.data)


class ConversationStatusTrackerDetail(generics.RetrieveUpdateAPIView):
    serializer_class = ConversationStatusTrackerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        slug = self.kwargs["slug"]
        user = self.request.user

        try:
            conversation = Conversation.objects.get(slug=slug)
        except Conversation.DoesNotExist:
            raise PermissionDenied("Conversation not found.")

        obj, _ = ConversationStatusTracker.objects.get_or_create(
            user=user, conversation=conversation
        )
        return obj


class ConversationStatusTrackerListView(generics.ListAPIView):
    serializer_class = ConversationStatusTrackerSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ConversationStatusTracker.objects.filter(user=self.request.user)


class ConversationReadView(APIView):
    authentication_classes = [ServiceJWTAuthentication, JWTAuthentication]
    permission_classes = [IsAuthenticated, IsConversationParticipant]

    def post(self, request, slug):
        conv = get_object_or_404(Conversation, slug=slug)
        last_msg = ChatMessage.objects.filter(conversation=conv).order_by("-created_at").first()

        tracker, _ = ConversationStatusTracker.objects.get_or_create(
            user=request.user, conversation=conv
        )
        tracker.last_read_message = last_msg
        tracker.last_read_at = timezone.now()
        tracker.unread_count = 0
        tracker.save(update_fields=["last_read_message", "last_read_at", "unread_count"])

        # Optional: return the user’s per-conversation unread map
        unread_map = {
            t.conversation.slug: t.unread_count
            for t in ConversationStatusTracker.objects
                    .filter(user=request.user)
                    .select_related("conversation")
        }
        return Response({"conversation": slug, "unreads": unread_map})





class UnreadsListView(APIView):
    authentication_classes = [ServiceJWTAuthentication, JWTAuthentication]
    permission_classes = [IsAuthenticated]
    def get(self, request):
        data = {
            t.conversation.slug: t.unread_count
            for t in ConversationStatusTracker.objects
                .filter(user=request.user)
                .select_related("conversation")
        }
        return Response({"unreads": data})




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mention_autocomplete(request):
    """API endpoint for mention autocomplete"""
    query = request.GET.get('q', '').strip()
    conversation_slug = request.GET.get('conversation_id')  # This is actually a slug

    if not query or len(query) < 2:
        return JsonResponse({'suggestions': []})

    try:
        conversation = Conversation.objects.get(slug=conversation_slug)  # Use slug

        # Verify user is a participant
        if not ConversationParticipant.objects.filter(user=request.user, conversation=conversation).exists():
            return JsonResponse({'error': 'Not a participant'}, status=403)

        suggestions = get_mentionable_objects_for_conversation(conversation, query)
        return JsonResponse({'suggestions': suggestions})
    except Conversation.DoesNotExist:
        return JsonResponse({'suggestions': []})


def get_mentionable_objects_for_conversation(conversation, query=""):
    """Updated to return proper autocomplete format"""
    mentionables = []

    # Users in conversation
    participants = conversation.participants.select_related('user').filter(
        user__username__icontains=query
    )[:10]  # Limit results

    for participant in participants:
        mentionables.append({
            'type': 'user',
            'id': str(participant.user.id),
            'username': participant.user.username,
            'display_name': participant.user.get_full_name() or participant.user.username,
            'mention_text': f"@{participant.user.username}"
        })

    # Add groups if applicable
    # Your group logic here

    return mentionables





from rest_framework.decorators import action
from rest_framework.response import Response



class ChatMessageViewSet(viewsets.ModelViewSet):
    serializer_class = ChatMessageSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Only return messages from conversations the user participates in"""
        return ChatMessage.objects.filter(
            conversation__participants__user=self.request.user
        ).select_related('sender', 'conversation').prefetch_related('reactions', 'mentions')

    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """Add or remove a reaction to a message"""
        message = self.get_object()

        # Verify user is a participant in the conversation
        if not ConversationParticipant.objects.filter(
            user=request.user,
            conversation=message.conversation
        ).exists():
            return Response({'error': 'Not authorized'}, status=403)

        reaction_name = request.data.get('reaction_name')

        if not reaction_name:
            return Response({'error': 'Reaction name is required'}, status=400)

        # Toggle reaction - remove if exists, add if doesn't
        reaction, created = MessageReaction.objects.get_or_create(
            message=message,
            user=request.user,
            reaction_name=reaction_name
        )

        if not created:
            # Reaction already exists, remove it
            reaction.delete()
            return Response({'action': 'removed', 'reaction_name': reaction_name})

        return Response({
            'action': 'added',
            'reaction_name': reaction_name,
            'reaction': MessageReactionSerializer(reaction).data
        })

    @action(detail=True, methods=['get'])
    def reactions(self, request, pk=None):
        """Get all reactions for a message"""
        message = self.get_object()
        reactions = message.reactions.all()
        return Response(MessageReactionSerializer(reactions, many=True).data)