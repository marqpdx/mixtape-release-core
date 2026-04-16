# profiles/api/views.py

from rest_framework import generics, status
from django.utils import timezone
from django.db import transaction
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

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
