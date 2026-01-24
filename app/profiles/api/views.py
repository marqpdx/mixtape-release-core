# profiles/api/views.py

from rest_framework import generics
from rest_framework.permissions import AllowAny

from profiles.models import UserProfile

from .serializers import MemberSerializer


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


class MemberDetailView(generics.RetrieveAPIView):
    """
    GET /api/members/<username>/

    Retrieve a single member by username (public).
    Returns combined User + Profile data.
    """
    permission_classes = [AllowAny]
    serializer_class = MemberSerializer
    queryset = UserProfile.objects.select_related("user").filter(
        deleted_at__isnull=True,
        user__is_active=True
    )
    lookup_field = "user__username"
    lookup_url_kwarg = "username"


# Phase 2: Add update/delete views with proper permissions
# class MemberUpdateView(generics.UpdateAPIView):
#     """
#     PATCH /api/members/<username>/
#     Update member profile (authenticated, own profile only)
#     """
#     permission_classes = [IsAuthenticated, IsOwnerOrReadOnly]
#     serializer_class = MemberUpdateSerializer
#     queryset = UserProfile.objects.all()
#     lookup_field = 'user__username'
#     lookup_url_kwarg = 'username'
