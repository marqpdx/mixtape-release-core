# profiles/api/views.py

from rest_framework import generics, status
from django.core.mail import send_mail
from django.utils import timezone
from django.db import transaction
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from profiles.models import UserProfile

from .serializers import MemberSerializer, MemberUpdateSerializer
from .permissions import IsProfileOwnerOrStaff


class MemberListView(generics.ListAPIView):
    """
    GET /api/members/

    List all members (public).
    Returns combined User + Profile data.
    """
    permission_classes = [AllowAny]
    serializer_class = MemberSerializer
    queryset = UserProfile.objects.select_related("user").filter(
        deleted_at__isnull=True,  # Exclude soft-deleted profiles
        user__is_active=True       # Only active users
    ).order_by("-created_at")


class MemberMeView(generics.RetrieveAPIView):
    """
    GET /api/members/me

    Retrieve the current authenticated member profile.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = MemberSerializer

    def get_object(self):
        return UserProfile.objects.select_related("user").get(
            user=self.request.user,
            deleted_at__isnull=True,
            user__is_active=True,
        )


class MemberDetailUpdateDeleteView(generics.RetrieveUpdateDestroyAPIView):
    """
    PATCH /api/members/<username>
    DELETE /api/members/<username>

    Update or soft-delete a member profile (owner or staff only).
    """
    serializer_class = MemberUpdateSerializer
    queryset = UserProfile.objects.select_related("user").filter(
        deleted_at__isnull=True,
        user__is_active=True,
    )
    lookup_field = "user__username"
    lookup_url_kwarg = "username"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [AllowAny()]
        return [IsAuthenticated(), IsProfileOwnerOrStaff()]

    def get_serializer_class(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return MemberSerializer
        return MemberUpdateSerializer

    def perform_update(self, serializer):
        serializer.save(updated_at=timezone.now())

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.deleted_at = instance.deleted_at or timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberContactView(APIView):
    """
    POST /api/members/<username>/contact

    Relay a contact message to a member without exposing their email.
    Sender email is pre-filled from auth but can be overridden.
    If save_email=True and the authenticated user has no email, saves the
    provided sender_email to their account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, username):
        from django.contrib.auth import get_user_model
        from django.shortcuts import get_object_or_404

        recipient_profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__username=username,
            deleted_at__isnull=True,
            user__is_active=True,
        )
        recipient_email = recipient_profile.user.email
        if not recipient_email:
            return Response(
                {"detail": "This member has not provided an email address."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        sender_name = (request.data.get("sender_name") or "").strip()
        sender_email = (request.data.get("sender_email") or "").strip()
        message = (request.data.get("message") or "").strip()
        save_email = bool(request.data.get("save_email", False))

        if not sender_email or not message:
            return Response(
                {"detail": "sender_email and message are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subject = f"Message via Crossroads from {sender_name or sender_email}"
        body = f"{message}\n\n---\nSent via Crossroads\nFrom: {sender_name or '(not provided)'} <{sender_email}>"

        send_mail(
            subject=subject,
            message=body,
            from_email=sender_email,
            recipient_list=[recipient_email],
            fail_silently=False,
        )

        if save_email and not request.user.email:
            User = get_user_model()
            User.users.filter(pk=request.user.pk).update(email=sender_email)

        return Response({"status": "sent"})


class MemberPreferencesView(generics.GenericAPIView):
    """
    GET  /api/members/me/preferences  — return current preferences dict
    PATCH /api/members/me/preferences — merge updates into preferences dict
    """
    permission_classes = [IsAuthenticated]

    def get_profile(self):
        return UserProfile.objects.get(user=self.request.user, deleted_at__isnull=True)

    def get(self, request):
        profile = self.get_profile()
        return Response(profile.preferences or {})

    def patch(self, request):
        profile = self.get_profile()
        updates = request.data
        if not isinstance(updates, dict):
            return Response({"detail": "Expected a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        profile.preferences = {**(profile.preferences or {}), **updates}
        profile.save(update_fields=["preferences", "updated_at"])
        return Response(profile.preferences)
