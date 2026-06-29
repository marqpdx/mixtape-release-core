# chat/api/views.py

import logging

from django.db import transaction
from django.db.models import Count, Max, Q
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
    ConversationKeyBundle,
    ConversationParticipant,
    ConversationRetentionPolicy,
    ConversationStatusTracker,
    MessageReaction,
    ParticipantVerification,
    TrustProfile,
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

                # F-001 (LW-D3): also match on trust_profile — returning an existing Standard conversation
        # when the caller requested Private or Ephemeral would silently drop E2E encryption.
        requested_profile = request.data.get("trust_profile", TrustProfile.STANDARD)
        for convo in existing:
                    convo_users = convo.participants.values_list("user__username", flat=True)
                    if set(convo_users) == set(usernames) and convo.trust_profile == requested_profile:
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

    # LW-C3: Private/Ephemeral clients encrypt the blob with the conversation key
    # before upload and send the AES-GCM IV alongside it. The server then holds
    # opaque ciphertext — it cannot validate the audio MIME or transcribe it.
    audio_iv = (request.data.get("iv") or "").strip()
    try:
        audio_key_version = int(request.data.get("key_version") or 1)
    except (TypeError, ValueError):
        audio_key_version = 1

    # M4 (LW-D3): clamp audio_key_version to the max known bundle version, matching the M1
    # fix for text messages. Prevents a participant from inflating the version to manipulate
    # pruning (premature or indefinitely deferred bundle deletion).
    if audio_iv:
        max_v = ConversationKeyBundle.objects.filter(
            conversation=conversation
        ).aggregate(max_v=Max("key_version"))["max_v"] or 1
        audio_key_version = min(max(audio_key_version, 1), max_v)
    content_type = (audio_file.content_type or "").lower().split(";")[0].strip()

    if not audio_iv and content_type not in ALLOWED_AUDIO_MIMES:
        # MIME validation — only meaningful for plaintext (Standard) audio.
        # Encrypted ciphertext arrives as application/octet-stream and skips this check.
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
        audio_iv=audio_iv,
        audio_key_version=audio_key_version if audio_iv else 1,
        # Server holds ciphertext only for encrypted audio — nothing to transcribe
        # (Private/Ephemeral has no AI features, per ADR-0046).
        transcript_status=None if audio_iv else "pending",
    )

    if not audio_iv:
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

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def my_devices(request):
    """
    GET  — list the current user's own active device sessions.
    POST — create or upsert a device session (client-generated UUID). Phase C LW-C2.
           Body: { "device_id": "<uuid>", "platform": "web"|"ios"|"android", "device_name": "<str>" }
    """
    if request.method == "POST":
        device_id = request.data.get("device_id")
        if not device_id:
            return Response({"detail": "device_id required."}, status=status.HTTP_400_BAD_REQUEST)
        platform = request.data.get("platform", "web")
        device_name = request.data.get("device_name", "")[:200]

        device, _ = UserDeviceSession.objects.get_or_create(
            device_id=device_id,
            user=request.user,
            defaults={"platform": platform, "device_name": device_name, "is_active": True},
        )
        device.last_seen_at = timezone.now()
        device.is_active = True
        device.save(update_fields=["last_seen_at", "is_active", "updated_at"])
        return Response(UserDeviceSessionSerializer(device).data, status=status.HTTP_200_OK)

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


def _rotation_interval(retention_period: str):
    """Returns the rotation interval for an Ephemeral conversation's retention period.
    Formula: retention_period / 4, clamped to min 6h / max 7d. LW-D2."""
    from datetime import timedelta
    PERIOD_DAYS = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "1y": 365}
    days = PERIOD_DAYS.get(retention_period)
    if not days:
        return None
    interval = timedelta(days=days) / 4
    return max(timedelta(hours=6), min(interval, timedelta(days=7)))


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
        if (
            conversation.trust_profile == TrustProfile.EPHEMERAL
            and policy.enforcement_enabled
            and policy.retention_period != ConversationRetentionPolicy.RetentionPeriod.INDEFINITE
        ):
            interval = _rotation_interval(policy.retention_period)
            if interval:
                policy.next_rotation_due_at = timezone.now() + interval
                policy.save(update_fields=["next_rotation_due_at", "updated_at"])
        return Response(ConversationRetentionPolicySerializer(policy).data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def register_device_key(request):
    """
    Register the calling device's ECDH public key (JWK format). Phase C LW-C2.
    Body: { "device_id": "<uuid>", "public_key": "<JWK JSON string>" }
    """
    device_id = request.data.get("device_id")
    public_key = request.data.get("public_key")

    if not device_id or not public_key:
        return Response(
            {"detail": "device_id and public_key required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    device = get_object_or_404(UserDeviceSession, device_id=device_id, user=request.user, is_active=True)
    device.public_key = public_key
    device.save(update_fields=["public_key", "updated_at"])

    logger.info("[livewire/keys] Device %s registered public key for user %s", device_id, request.user.username)
    return Response({"registered": True})


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def conversation_my_key(request, slug):
    """
    Fetch the encrypted key bundle for the calling device in this conversation. Phase C LW-C2.
    Device identified via X-Device-ID header or `device_id` query param.
    Returns the latest key version by default, or a specific version via
    `?version=N` (LW-C4) — needed to decrypt history from before a rotation.
    404 if no bundle exists for the requested version.
    """
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(user=request.user, conversation=conversation).exists():
        return Response({"detail": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

    if conversation.trust_profile == TrustProfile.STANDARD:
        return Response(
            {"detail": "Key bundles are only for Private and Ephemeral conversations."},
            status=status.HTTP_403_FORBIDDEN,
        )

    device_id = request.headers.get("X-Device-ID") or request.query_params.get("device_id")
    if not device_id:
        return Response(
            {"detail": "X-Device-ID header or device_id query param required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    device = get_object_or_404(UserDeviceSession, device_id=device_id, user=request.user, is_active=True)

    bundle_qs = ConversationKeyBundle.objects.filter(conversation=conversation, recipient_device=device)

    requested_version = request.query_params.get("version")
    if requested_version is not None:
        try:
            bundle = bundle_qs.filter(key_version=int(requested_version)).first()
        except (TypeError, ValueError):
            return Response({"detail": "version must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
    else:
        bundle = bundle_qs.order_by("-key_version").first()

    if not bundle:
        return Response(
            {"detail": "No key bundle found for this device."},
            status=status.HTTP_404_NOT_FOUND,
        )

    response_data = {
        "encrypted_key": bundle.encrypted_key,
        "nonce": bundle.nonce,
        "ephemeral_public_key": bundle.ephemeral_public_key,
        "key_version": bundle.key_version,
    }
    if conversation.trust_profile == TrustProfile.EPHEMERAL:
        try:
            p = conversation.retention_policy
            response_data["next_rotation_due_at"] = (
                p.next_rotation_due_at.isoformat() if p.next_rotation_due_at else None
            )
        except ConversationRetentionPolicy.DoesNotExist:
            response_data["next_rotation_due_at"] = None
    return Response(response_data)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsAuthenticated])
def conversation_post_keys(request, slug):
    """
    Post encrypted key bundles for participant devices. Phase C LW-C2.
    Called at conversation creation and on key rotation (LW-C4).
    All bundles in a single POST share the same key_version (next increment).
    Body: { "bundles": [{ "device_id": "<uuid>", "encrypted_key": "<b64>", "nonce": "<b64>" }] }
    """
    conversation = get_object_or_404(Conversation, slug=slug)

    if not ConversationParticipant.objects.filter(user=request.user, conversation=conversation).exists():
        return Response({"detail": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

    if conversation.trust_profile == TrustProfile.STANDARD:
        return Response(
            {"detail": "Key bundles are only for Private and Ephemeral conversations."},
            status=status.HTTP_403_FORBIDDEN,
        )

    bundles = request.data.get("bundles", [])
    if not bundles:
        return Response({"detail": "bundles array required."}, status=status.HTTP_400_BAD_REQUEST)

    # M2: verify submitted bundles cover all active participant devices with registered public keys.
    participant_user_ids = ConversationParticipant.objects.filter(
        conversation=conversation
    ).values_list("user_id", flat=True)
    required_device_ids = set(
        UserDeviceSession.objects.filter(
            user_id__in=participant_user_ids,
            is_active=True,
        ).exclude(public_key="").values_list("device_id", flat=True)
    )
    # F-001 GPT (LW-D3): only count bundles that have all required wrapping fields toward the
    # coverage check. A bundle with just device_id but missing encrypted_key/nonce/ephemeral_public_key
    # would be skipped during insertion but still counted here, letting a caller satisfy the M2
    # preflight while leaving one device without a valid bundle.
    submitted_device_ids = {
        item.get("device_id") for item in bundles
        if item.get("device_id") and item.get("encrypted_key") and item.get("nonce") and item.get("ephemeral_public_key")
    }
    missing_devices = required_device_ids - submitted_device_ids
    if missing_devices:
        return Response(
            {"detail": "Missing bundles for required participant devices.", "missing": list(missing_devices)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    created_count = 0
    errors = []

    with transaction.atomic():
        # Lock the conversation row so concurrent rotation calls serialize here,
        # preventing two clients from computing the same next_version. LW-D2.
        conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)

        current_max = ConversationKeyBundle.objects.filter(
            conversation=conversation
        ).aggregate(max_v=Max("key_version"))["max_v"] or 0
        next_version = current_max + 1

        for item in bundles:
            device_id = item.get("device_id")
            encrypted_key = item.get("encrypted_key")
            nonce = item.get("nonce")
            ephemeral_public_key = item.get("ephemeral_public_key")

            if not all([device_id, encrypted_key, nonce, ephemeral_public_key]):
                errors.append(f"Bundle missing required fields: {item}")
                continue

            try:
                device = UserDeviceSession.objects.get(device_id=device_id, is_active=True)
            except UserDeviceSession.DoesNotExist:
                errors.append(f"Device not found or inactive: {device_id}")
                continue

            # H1: verify device owner is a current conversation participant.
            if not ConversationParticipant.objects.filter(
                user=device.user, conversation=conversation
            ).exists():
                errors.append(f"Device owner is not a conversation participant: {device_id}")
                continue

            ConversationKeyBundle.objects.create(
                conversation=conversation,
                recipient_device=device,
                encrypted_key=encrypted_key,
                nonce=nonce,
                ephemeral_public_key=ephemeral_public_key,
                key_version=next_version,
            )
            created_count += 1

        # LW-D2: reset next_rotation_due_at on successful rotation for Ephemeral.
        # M3: use get_or_create so the policy exists after first key distribution,
        # ensuring a subsequent retention PATCH can always find and update it.
        if created_count > 0 and conversation.trust_profile == TrustProfile.EPHEMERAL:
            # F-002/F-005 (LW-D3): if this is the first key posting, create the policy with
            # enforcement_enabled=True and a default retention period so the Ephemeral contract
            # (deletion + key rotation) activates even if the user never PATCHes /retention.
            policy, _ = ConversationRetentionPolicy.objects.get_or_create(
                conversation=conversation,
                defaults={
                    "enforcement_enabled": True,
                    "retention_period": ConversationRetentionPolicy.RetentionPeriod.SEVEN_DAYS,
                },
            )
            if (
                policy.enforcement_enabled
                and policy.retention_period != ConversationRetentionPolicy.RetentionPeriod.INDEFINITE
            ):
                interval = _rotation_interval(policy.retention_period)
                if interval:
                    policy.next_rotation_due_at = timezone.now() + interval
                    policy.save(update_fields=["next_rotation_due_at", "updated_at"])

    logger.info(
        "[livewire/keys] %d key bundles posted for conversation %s (v%d) by %s",
        created_count, slug, next_version, request.user.username,
    )

    # H2 (LW-D3): push a key_rotated event so other connected devices know to evict
    # their cached key and fetch the new bundle without waiting for next conversation open.
    if created_count > 0:
        from utils.chat.notify_socket_server import notify_socket_server_task
        notify_socket_server_task.delay({
            "event": "conversation:key_rotated",
            "slug": slug,
            "key_version": next_version,
        })

    response_status = status.HTTP_201_CREATED if created_count else status.HTTP_400_BAD_REQUEST
    return Response({"created": created_count, "key_version": next_version, "errors": errors}, status=response_status)
