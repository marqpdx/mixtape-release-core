# chat/api/views.py

import logging

from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from chat.api.serializers import (
    BaseConversationSerializer,
    ChatMessageSerializer,
    ConversationReadSerializer,
    ConversationRetentionPolicySerializer,
    ConversationSerializer,
    ConversationStatusTrackerSerializer,
    MessageReactionSerializer,
    ParticipantDeviceSerializer,
    UserDeviceSessionSerializer,
)
from chat.models import (
    ChatMessage,
    Conversation,
    ConversationAuditEvent,
    ConversationParticipant,
    ConversationRetentionPolicy,
    ConversationStatusTracker,
    MessageReaction,
    ParticipantVerification,
    UserDeviceSession,
)
from chat.permissions import IsConversationParticipant
from chat.utils import generate_conversation_title
from livewire.auth import (
    ServiceJWTAuthentication,  # your class that verifies SERVICE_JWT_SECRET
)
from livewire.permissions import (
    HasChatWriteScope,  # checks "chat:write" in request.auth_payload
)
from users.models import CustomUser

# from utils.activity import format_chat_message_log, log_activity
from utils.chat.notify_socket_server import notify_socket_server

from .serializers import ChatMessageSerializer

logger = logging.getLogger(__name__)


class MessagePagination(PageNumberPagination):
    """Pagination for chat messages"""
    page_size = 50
    page_size_query_param = "page_size"
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
@authentication_classes([ServiceJWTAuthentication, JWTAuthentication])
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
    try:
        participant = ConversationParticipant.objects.get(user=user, conversation=conversation)
    except ConversationParticipant.DoesNotExist:
        return Response(
            {"detail": "Not a participant of this conversation."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == "GET":
        # History is gated to the participant's join date — new members never see past messages.
        messages = ChatMessage.objects.filter(
            conversation=conversation,
            created_at__gte=participant.joined_at,
        ).select_related("sender").prefetch_related("reactions__user", "mentions").order_by("-created_at")

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

        # Fan out new-message notifications to all participants except sender
        try:
            from activity.producers_chat import on_new_chat_message
            recipient_users = list(
                CustomUser.objects.filter(
                    conversationparticipant__conversation=conversation
                ).exclude(pk=user.pk)
            )
            on_new_chat_message(
                message=message,
                conversation=conversation,
                recipients=recipient_users,
            )
        except Exception:
            logger.exception("on_new_chat_message failed for conversation=%s", conversation.slug)

        # Additional producer for group-scoped conversations
        try:
            cc = conversation.conversation_contexts.select_related(
                "context__content_type"
            ).first()
            if cc and cc.context.content_type.model == "group":
                from activity.producers_livewire import on_group_chat_message
                group = cc.context.anchor
                on_group_chat_message(
                    message=message, conversation=conversation, group=group,
                )
        except Exception:
            logger.exception("on_group_chat_message failed for conversation=%s", conversation.slug)

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
    query = request.GET.get("q", "").strip()
    conversation_slug = request.GET.get("conversation_id")  # This is actually a slug

    if not query or len(query) < 2:
        return JsonResponse({"suggestions": []})

    try:
        conversation = Conversation.objects.get(slug=conversation_slug)  # Use slug

        # Verify user is a participant
        if not ConversationParticipant.objects.filter(user=request.user, conversation=conversation).exists():
            return JsonResponse({"error": "Not a participant"}, status=403)

        suggestions = get_mentionable_objects_for_conversation(conversation, query)
        return JsonResponse({"suggestions": suggestions})
    except Conversation.DoesNotExist:
        return JsonResponse({"suggestions": []})


def get_mentionable_objects_for_conversation(conversation, query=""):
    """Updated to return proper autocomplete format"""
    mentionables = []

    # Users in conversation
    participants = conversation.participants.select_related("user").filter(
        user__username__icontains=query
    )[:10]  # Limit results

    for participant in participants:
        mentionables.append({
            "type": "user",
            "id": str(participant.user.id),
            "username": participant.user.username,
            "display_name": participant.user.get_full_name() or participant.user.username,
            "mention_text": f"@{participant.user.username}"
        })

    # Add groups if applicable
    # Your group logic here

    return mentionables





MAX_VOICE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_AUDIO_MIMES = {"audio/m4a", "audio/mp4", "audio/webm", "audio/ogg", "audio/mpeg", "audio/wav", "audio/aac"}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def conversation_voice_upload(request, slug):
    """
    POST /api/chat/conversations/<slug>/voice-upload/
    Multipart fields: audio (file), duration (float, seconds)

    Access: authenticated + conversation participant only.
    Returns 404 for non-participants to avoid leaking conversation existence.
    """
    # 404 for non-participants (per access control pattern — no info leak)
    conversation = get_object_or_404(
        Conversation,
        slug=slug,
        participants__user=request.user,
    )

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return Response({"error": "audio file is required."}, status=status.HTTP_400_BAD_REQUEST)

    # MIME validation
    content_type = (audio_file.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_AUDIO_MIMES:
        return Response(
            {"error": f"Unsupported audio type: {content_type}. Use M4A, WebM, or OGG."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Size cap
    if audio_file.size > MAX_VOICE_BYTES:
        return Response(
            {"error": "Audio file exceeds 10 MB limit."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    duration_seconds = None
    try:
        raw_duration = request.data.get("duration")
        if raw_duration is not None:
            duration_seconds = float(raw_duration)
    except (TypeError, ValueError):
        pass

    # Store via default_storage (same pattern as seed voice notes)
    import uuid as _uuid
    import os as _os
    from django.core.files.storage import default_storage
    from files.models import StoredFile

    ext = _os.path.splitext(audio_file.name or "voice.m4a")[1] or ".m4a"
    storage_key = f"chat/voice/{request.user.id}/{_uuid.uuid4()}{ext}"
    saved_path = default_storage.save(storage_key, audio_file)

    stored_file = StoredFile.objects.create(
        file_path=saved_path,
        file_name=audio_file.name or f"voice{ext}",
        file_type=content_type,
        file_size=audio_file.size,
        uploaded_by=request.user,
        source="chat_voice",
    )

    message = ChatMessage.objects.create(
        conversation=conversation,
        sender=request.user,
        text="",  # voice messages have no text body
        message_type="voice",
        audio_file=stored_file,
        audio_duration_seconds=duration_seconds,
        transcript_status="pending",
    )

    # Enqueue transcription
    from chat.tasks import transcribe_chat_message_task
    transcribe_chat_message_task.delay(str(message.id))

    # Notify other participants via activity pipeline
    try:
        from activity.producers_chat import on_new_chat_message
        recipient_users = list(
            CustomUser.objects.filter(
                conversationparticipant__conversation=conversation
            ).exclude(pk=request.user.pk)
        )
        on_new_chat_message(
            message=message,
            conversation=conversation,
            recipients=recipient_users,
        )
    except Exception:
        logger.exception("on_new_chat_message failed for voice message in conversation=%s", slug)

    return Response(ChatMessageSerializer(message).data, status=status.HTTP_201_CREATED)


from django.utils import timezone as tz
from rest_framework.decorators import action


# ---------------------------------------------------------------------------
# Phase B — Device verification endpoints
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_devices(request):
    """List the current user's own active device sessions."""
    devices = UserDeviceSession.objects.filter(
        user=request.user, is_active=True
    ).order_by("-last_seen_at")
    return Response(UserDeviceSessionSerializer(devices, many=True).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def revoke_device(request, device_id):
    """Deactivate one of the current user's own devices."""
    device = get_object_or_404(UserDeviceSession, device_id=device_id, user=request.user)
    device.is_active = False
    device.save(update_fields=["is_active", "updated_at"])
    logger.info(
        "[livewire/devices] Device %s revoked by user %s", device_id, request.user.username
    )
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def conversation_devices(request, slug):
    """
    List active devices for all participants in a Private or Ephemeral conversation.
    Each device record includes a `verified_by_me` flag for the calling user.
    Returns 403 for Standard conversations — device listing is not applicable.
    """
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(
        user=request.user, conversation=conversation
    ).exists():
        return Response({"detail": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

    if conversation.trust_profile == "standard":
        return Response(
            {"detail": "Device verification is not available for Standard conversations."},
            status=status.HTTP_403_FORBIDDEN,
        )

    participant_users = ConversationParticipant.objects.filter(
        conversation=conversation
    ).select_related("user")

    user_ids = [p.user_id for p in participant_users]
    devices = UserDeviceSession.objects.filter(
        user_id__in=user_ids, is_active=True
    ).select_related("user")

    verified_device_ids = set(
        ParticipantVerification.objects.filter(
            conversation=conversation,
            verifier=request.user,
        ).values_list("verified_device_id", flat=True)
    )

    serializer_ctx = {"verified_device_ids": verified_device_ids}

    grouped = []
    user_map = {p.user_id: p.user for p in participant_users}
    devices_by_user: dict = {}
    for device in devices:
        devices_by_user.setdefault(device.user_id, []).append(device)

    for user_id, user_obj in user_map.items():
        if user_obj == request.user:
            continue
        user_devices = devices_by_user.get(user_id, [])
        grouped.append({
            "username": user_obj.username,
            "display_name": user_obj.get_full_name() or user_obj.username,
            "devices": ParticipantDeviceSerializer(
                user_devices, many=True, context=serializer_ctx
            ).data,
        })

    return Response(grouped)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def trust_device(request, slug, device_id):
    """
    Mark a participant's device as verified within this conversation.
    Creates a ParticipantVerification record and emits a DEVICE_VERIFIED audit event.
    Only available in Private and Ephemeral conversations.
    """
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(
        user=request.user, conversation=conversation
    ).exists():
        return Response({"detail": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

    if conversation.trust_profile == "standard":
        return Response(
            {"detail": "Device verification is not available for Standard conversations."},
            status=status.HTTP_403_FORBIDDEN,
        )

    device = get_object_or_404(UserDeviceSession, device_id=device_id, is_active=True)

    if device.user == request.user:
        return Response(
            {"detail": "Cannot verify your own device."}, status=status.HTTP_400_BAD_REQUEST
        )

    if not ConversationParticipant.objects.filter(
        user=device.user, conversation=conversation
    ).exists():
        return Response(
            {"detail": "Device owner is not a participant in this conversation."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    verification, created = ParticipantVerification.objects.get_or_create(
        conversation=conversation,
        verifier=request.user,
        verified_device=device,
        defaults={"verified_user": device.user},
    )

    if created:
        if not device.is_trusted:
            device.is_trusted = True
            device.trusted_at = tz.now()
            device.save(update_fields=["is_trusted", "trusted_at", "updated_at"])

        ConversationAuditEvent.objects.create(
            conversation=conversation,
            actor=request.user,
            event_type=ConversationAuditEvent.EventType.DEVICE_VERIFIED,
            metadata={
                "verified_user": device.user.username,
                "device_id": str(device_id),
                "fingerprint": device.verification_fingerprint,
            },
        )

    return Response(
        {
            "verified": True,
            "created": created,
            "fingerprint": device.verification_fingerprint,
        },
        status=status.HTTP_200_OK,
    )


class ChatMessageViewSet(viewsets.ModelViewSet):
    serializer_class = ChatMessageSerializer
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Only return messages from conversations the user participates in"""
        return ChatMessage.objects.filter(
            conversation__participants__user=self.request.user
        ).select_related("sender", "conversation").prefetch_related("reactions", "mentions")

    @action(detail=True, methods=["post"])
    def react(self, request, pk=None):
        """Add or remove a reaction to a message"""
        message = self.get_object()

        # Verify user is a participant in the conversation
        if not ConversationParticipant.objects.filter(
            user=request.user,
            conversation=message.conversation
        ).exists():
            return Response({"error": "Not authorized"}, status=403)

        reaction_name = request.data.get("reaction_name")

        if not reaction_name:
            return Response({"error": "Reaction name is required"}, status=400)

        # Toggle reaction - remove if exists, add if doesn't
        reaction, created = MessageReaction.objects.get_or_create(
            message=message,
            user=request.user,
            reaction_name=reaction_name
        )

        if not created:
            # Reaction already exists, remove it
            reaction.delete()
            return Response({"action": "removed", "reaction_name": reaction_name})

        return Response({
            "action": "added",
            "reaction_name": reaction_name,
            "reaction": MessageReactionSerializer(reaction).data
        })

    @action(detail=True, methods=["get"])
    def reactions(self, request, pk=None):
        """Get all reactions for a message"""
        message = self.get_object()
        reactions = message.reactions.all()
        return Response(MessageReactionSerializer(reactions, many=True).data)


@api_view(["GET", "PATCH"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def conversation_retention(request, slug):
    """GET or PATCH the retention policy for a Conversation the user participates in."""
    user = request.user
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(user=user, conversation=conversation).exists():
        return Response({"detail": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

    policy, _ = ConversationRetentionPolicy.objects.get_or_create(conversation=conversation)

    if request.method == "GET":
        return Response(ConversationRetentionPolicySerializer(policy).data)

    serializer = ConversationRetentionPolicySerializer(policy, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
