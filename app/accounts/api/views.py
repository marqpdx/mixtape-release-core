# accounts/api/views.py

from django.contrib.auth import get_user_model
# from django.contrib.auth.models import Group  # Deferred to Phase 3
from django.db.models import Prefetch
from http import HTTPStatus
from rest_framework import status
from rest_framework import generics
from rest_framework import permissions, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.core.cache import cache

from profiles.models import UserProfile
from users.models import Role

from .serializers import UserCreateSerializer
from .serializers import UserSerializer
# from .serializers import GroupSerializer  # Deferred to Phase 3

User = get_user_model()


def csrf(request):
    return JsonResponse({'csrfToken': get_token(request)})


# ============================================================================
# UserViewSet - Now enabled for Phase 2+
# ============================================================================
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows users to be viewed.
    Read-only for now (list and retrieve only).
    """
    queryset = get_user_model().objects.none()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]  # Require authentication
    pagination_class = None

    def get_queryset(self):
        """
        Return all active users, prefetch roles for efficiency.
        """
        qs = get_user_model().objects.filter(
            is_active=True
        ).prefetch_related(
            Prefetch('roles', queryset=Role.objects.only('name'))
        ).select_related('profile').order_by('-date_joined')

        return qs


# ============================================================================
# DEFERRED: GroupViewSet (Phase 3)
# ============================================================================
# class GroupViewSet(viewsets.ModelViewSet):
#     """
#     API endpoint that allows groups to be viewed or edited.
#     """
#     queryset = Group.objects.all()
#     serializer_class = GroupSerializer
#     permission_classes = [permissions.AllowAny]


# class Identity(generics.RetrieveAPIView):
#     permission_classes = (IsAuthenticated,)
#     serializer_class = UserSerializer

#     def get_object(self):
#         return self.request.user



class CurrentUserIdentity(APIView):
    """
    GET /api/auth/me

    Returns the complete identity for the authenticated user:
    - Basic user info (id, username, email)
    - Permissions (is_superuser, is_staff)
    - Roles
    - Profile info
    - Group memberships

    This is the SINGLE SOURCE OF TRUTH for frontend identity.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Try cache first (5 minute TTL)
        cache_key = f"user_identity:{user.id}"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached, status=status.HTTP_200_OK)

        try:
            # Get profile
            profile = UserProfile.objects.filter(user=user).first()

            # Get user's groups (assuming CustomUser has a groups field)
            groups = user.groups.all() if hasattr(user, 'groups') else []

            # Build roles list
            roles = []
            if user.is_superuser:
                roles.append("admin")
            if user.is_staff:
                roles.append("staff")

            # Add custom roles if they exist
            if hasattr(user, 'roles'):
                roles.extend(list(user.roles.values_list('name', flat=True)))

            # Default to member if has groups
            if not roles and groups.exists():
                roles.append("member")

            # Compute user permissions
            from groups.services.permissions import PermissionService
            permissions_data = PermissionService.compute_user_permissions(user)

            response_data = {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "roles": list(set(roles)),  # Unique list
                "profile": {
                    "id": str(profile.id),
                    "slug": profile.slug,
                    "display_name": profile.display_name,
                    "quick_intro": profile.quick_intro,
                    "avatar_url": profile.avatar_url,
                } if profile else None,
                "groups": [
                    {
                        "id": str(group.id),
                        "name": group.name,
                        "slug": group.slug,
                    }
                    for group in groups
                ],
                "permissions": permissions_data,
            }

            # Cache for 5 minutes
            cache.set(cache_key, response_data, 300)

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



@api_view(["GET"])
@permission_classes([AllowAny])
def check_username(request, username):
    """
    GET /api/auth/check-username/<username>

    Check if a username is available (for signup/registration).
    Returns { "available": true/false }
    """
    try:
        exists = User.objects.filter(username=username).exists()
        return Response(
            {"available": not exists, "username": username},
            status=status.HTTP_200_OK
        )
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def refresh_permissions(request):
    """
    GET /api/auth/permissions/refresh

    Refresh and return the current user's permissions.
    Useful after role/membership changes.
    Clears the identity cache and returns fresh permissions.
    """
    try:
        user = request.user

        # Clear cached identity
        cache_key = f"user_identity:{user.id}"
        cache.delete(cache_key)

        # Compute fresh permissions
        from groups.services.permissions import PermissionService
        permissions_data = PermissionService.compute_user_permissions(user)

        return Response(permissions_data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['POST'])
@permission_classes([AllowAny])
def user_create_view(request):
    print("🔥 Reached the view!")  # ✅ Check if this prints
    serializer = UserCreateSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        error_messages = {field: str(error) for field, error in serializer.errors.items()}
        print('serializer.errors', error_messages)
        return Response(data={
            **error_messages,
            'success': False
        }, status=HTTPStatus.BAD_REQUEST)

    try:
        user = serializer.save()
    except Exception as e:
        print(f"Error creating user: {e}")
        return Response(data={
            'error': 'An error occurred while creating the user.',
            'success': False
        }, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    return Response(data={
        'message': 'Record Created.',
        'success': True
    }, status=HTTPStatus.OK)
