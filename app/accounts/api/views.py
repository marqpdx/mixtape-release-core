# accounts/api/views.py

from http import HTTPStatus
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

# from django.contrib.auth.models import Group  # Deferred to Phase 3
from django.db.models import Prefetch
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from .throttles import SignupThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from profiles.models import UserProfile
from users.models import Role

from django.contrib.contenttypes.models import ContentType
from groups.models import GroupMembership

from .serializers import MemberDirectorySerializer, UserCreateSerializer, UserSerializer


# from .serializers import GroupSerializer  # Deferred to Phase 3

User = get_user_model()
logger = logging.getLogger(__name__)

class UsernameCheckThrottle(AnonRateThrottle):
    rate = "10/min"


IMPERSONATION_ORIGINAL_USER_ID_KEY = "impersonation_original_user_id"
IMPERSONATION_TARGET_USER_ID_KEY = "impersonation_target_user_id"
IMPERSONATION_STARTED_AT_KEY = "impersonation_started_at"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        settings.JWT_COOKIE_NAME,
        refresh_token,
        secure=settings.JWT_COOKIE_SECURE,
        httponly=True,
        samesite=settings.JWT_COOKIE_SAMESITE,
        path="/",
        domain=getattr(settings, "SESSION_COOKIE_DOMAIN", None),
    )


def _build_auth_payload(user):
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token
    access["username"] = user.username

    return {
        "success": True,
        "access": str(access),
        "access_expires": access["exp"],
        "refresh": str(refresh),
        "refresh_expires": refresh["exp"],
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
        },
    }


def _build_impersonation_payload(request, user):
    impersonation_original_id = request.session.get(IMPERSONATION_ORIGINAL_USER_ID_KEY)
    impersonation_target_id = request.session.get(IMPERSONATION_TARGET_USER_ID_KEY)
    if impersonation_original_id and impersonation_target_id and str(user.id) == str(impersonation_target_id):
        original_user = User.objects.filter(id=impersonation_original_id).first()
        return {
            "is_impersonating": True,
            "started_at": request.session.get(IMPERSONATION_STARTED_AT_KEY),
            "impersonated_by": {
                "id": str(original_user.id),
                "username": original_user.username,
                "first_name": original_user.first_name,
                "is_superuser": original_user.is_superuser,
            } if original_user else None,
        }
    return {
        "is_impersonating": False,
        "started_at": None,
        "impersonated_by": None,
    }


def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


# ============================================================================
# UserViewSet - Now enabled for Phase 2+
# ============================================================================
class UserViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only member directory. Returns users who share at least one group with the caller.
    Superusers see all active users.
    """
    queryset = get_user_model().objects.none()
    serializer_class = MemberDirectorySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        base_qs = get_user_model().objects.filter(
            is_active=True
        ).prefetch_related(
            Prefetch("roles", queryset=Role.objects.only("name"))
        ).select_related("profile").order_by("-date_joined")

        if user.is_superuser:
            return base_qs

        user_ct = ContentType.objects.get_for_model(User)
        shared_group_ids = GroupMembership.objects.filter(
            member_content_type=user_ct,
            member_object_id=user.pk,
            is_active=True,
        ).values_list("group_id", flat=True)

        peer_user_ids = GroupMembership.objects.filter(
            group_id__in=shared_group_ids,
            member_content_type=user_ct,
            is_active=True,
        ).values_list("member_object_id", flat=True)

        return base_qs.filter(pk__in=peer_user_ids)


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
            response_data = dict(cached)
            response_data["impersonation"] = _build_impersonation_payload(request, user)
            return Response(response_data, status=status.HTTP_200_OK)

        try:
            # Get profile
            profile = UserProfile.objects.filter(user=user).first()

            # Get user's groups (assuming CustomUser has a groups field)
            groups = user.groups.all() if hasattr(user, "groups") else []

            # Build roles list
            roles = []
            if user.is_superuser:
                roles.append("admin")
            if user.is_staff:
                roles.append("staff")

            # Add custom roles if they exist
            if hasattr(user, "roles"):
                roles.extend(list(user.roles.values_list("name", flat=True)))

            # Default to member if has groups
            if not roles and groups.exists():
                roles.append("member")

            # Compute user permissions
            from groups.services.permissions import PermissionService
            permissions_data = PermissionService.compute_user_permissions(user)

            from accounts.services import user_has_helper_access
            can_use_beacon = user_has_helper_access(user)

            response_data = {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "is_superuser": user.is_superuser,
                "is_staff": user.is_staff,
                "can_use_beacon": can_use_beacon,
                "can_use_lighthouse": can_use_beacon,  # backward compat alias
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

            response_data["impersonation"] = _build_impersonation_payload(request, user)

            # Cache for 5 minutes
            cache_payload = dict(response_data)
            cache_payload.pop("impersonation", None)
            cache.set(cache_key, cache_payload, 300)

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class AssumeUserView(APIView):
    """
    POST /api/auth/assume
    Superuser-only: start impersonating another user by username.
    Returns JWTs for assumed user and stores original/target in session.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        actor = request.user
        if not actor.is_superuser:
            return Response({"detail": "Superuser access required."}, status=status.HTTP_403_FORBIDDEN)

        username = str(request.data.get("username", "")).strip()
        if not username:
            return Response({"detail": "username is required."}, status=status.HTTP_400_BAD_REQUEST)

        target = User.objects.filter(username=username, is_active=True).first()
        if not target:
            return Response({"detail": "Target user not found."}, status=status.HTTP_404_NOT_FOUND)
        if target.id == actor.id:
            return Response({"detail": "Cannot assume yourself."}, status=status.HTTP_400_BAD_REQUEST)

        request.session[IMPERSONATION_ORIGINAL_USER_ID_KEY] = str(actor.id)
        request.session[IMPERSONATION_TARGET_USER_ID_KEY] = str(target.id)
        request.session[IMPERSONATION_STARTED_AT_KEY] = timezone.now().isoformat()
        request.session.modified = True

        cache.delete(f"user_identity:{actor.id}")
        cache.delete(f"user_identity:{target.id}")

        logger.info(
            "Impersonation started: actor=%s target=%s ip=%s",
            actor.username,
            target.username,
            request.META.get("REMOTE_ADDR"),
        )

        payload = _build_auth_payload(target)
        response = Response(payload, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, payload["refresh"])
        return response


class ExitAssumeUserView(APIView):
    """
    POST /api/auth/assume/exit
    End impersonation and restore original user tokens.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        original_user_id = request.session.get(IMPERSONATION_ORIGINAL_USER_ID_KEY)
        target_user_id = request.session.get(IMPERSONATION_TARGET_USER_ID_KEY)

        if not original_user_id or not target_user_id:
            return Response({"detail": "Not currently impersonating."}, status=status.HTTP_400_BAD_REQUEST)

        original_user = User.objects.filter(id=original_user_id, is_active=True).first()
        if not original_user:
            return Response({"detail": "Original user not found."}, status=status.HTTP_404_NOT_FOUND)
        if not original_user.is_superuser:
            return Response({"detail": "Original user is not authorized."}, status=status.HTTP_403_FORBIDDEN)

        request.session.pop(IMPERSONATION_ORIGINAL_USER_ID_KEY, None)
        request.session.pop(IMPERSONATION_TARGET_USER_ID_KEY, None)
        request.session.pop(IMPERSONATION_STARTED_AT_KEY, None)
        request.session.modified = True

        cache.delete(f"user_identity:{original_user.id}")
        cache.delete(f"user_identity:{target_user_id}")

        logger.info(
            "Impersonation ended: actor=%s target_id=%s ip=%s",
            original_user.username,
            target_user_id,
            request.META.get("REMOTE_ADDR"),
        )

        payload = _build_auth_payload(original_user)
        response = Response(payload, status=status.HTTP_200_OK)
        _set_refresh_cookie(response, payload["refresh"])
        return response


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([UsernameCheckThrottle])
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



@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SignupThrottle])
def user_create_view(request):
    serializer = UserCreateSerializer(data=request.data, context={"request": request})
    if not serializer.is_valid():
        error_messages = {field: str(error) for field, error in serializer.errors.items()}
        return Response(data={
            **error_messages,
            "success": False
        }, status=HTTPStatus.BAD_REQUEST)

    try:
        user = serializer.save()
    except Exception as e:
        logger.error("Error creating user: %s", e)
        return Response(data={
            "error": "An error occurred while creating the user.",
            "success": False
        }, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    return Response(data={
        "message": "Record Created.",
        "success": True
    }, status=HTTPStatus.OK)
