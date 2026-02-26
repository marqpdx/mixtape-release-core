# fundamentals/api/follow_views.py

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from fundamentals.models import Follow
from fundamentals.services.follow_service import (
    follow_user,
    unfollow_user,
    get_followers_count,
    get_following_count,
    is_following,
    FollowError,
)

User = get_user_model()


class FollowUserView(APIView):
    """
    POST /api/follows   → follow a user
    Body: { "user_id": "<uuid>" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        target = get_object_or_404(User, pk=user_id)

        try:
            follow, created = follow_user(follower=request.user, target=target)
        except FollowError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "id": str(follow.id),
            "following": str(target.id),
            "created": created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class UnfollowUserView(APIView):
    """
    DELETE /api/follows/<uuid:user_id>   → unfollow a user
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, user_id):
        target = get_object_or_404(User, pk=user_id)
        removed = unfollow_user(follower=request.user, target=target)
        if not removed:
            return Response({"error": "Not following this user"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FollowingListView(generics.ListAPIView):
    """
    GET /api/follows   → list users the current user follows
    """
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        follows = Follow.objects.filter(
            follower=request.user,
            deleted_at__isnull=True,
        ).select_related("following", "following__profile").order_by("-created_at")

        results = []
        for f in follows:
            user = f.following
            results.append({
                "id": str(f.id),
                "user_id": str(user.id),
                "username": user.username,
                "display_name": user.get_full_name() or user.username,
                "followed_at": f.created_at.isoformat(),
            })

        return Response(results)


class FollowStatusView(APIView):
    """
    GET /api/follows/<uuid:user_id>/status → check follow status + counts
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        target = get_object_or_404(User, pk=user_id)
        return Response({
            "is_following": is_following(follower=request.user, target=target),
            "followers_count": get_followers_count(target),
            "following_count": get_following_count(target),
        })
