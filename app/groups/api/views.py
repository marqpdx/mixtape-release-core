# groups/api/views.py

import json

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

# from utils.email.shortcode import generate_shortcode
# from utils.tasks import send_transactional_email_task
# ============================================================================
# PHASE 3+: Writing Integration (Deferred)
# ============================================================================
# from writing.api.serializers import WritingPieceSerializer, WritingPlacementSerializer, WritingWorkingCopySerializer
# from writing.models import WritingPiece, WritingPlacement, WritingWorkingCopy
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes

# from threadworks.api.views import StandardResultsSetPagination  # PHASE 3: Deferred
from rest_framework.response import Response

from groups.api.permissions import CanInviteMembers
from groups.api.serializers import (
    GroupCreateSerializer,
    GroupDetailSerializer,
    GroupInvitationSerializer,
    GroupListSerializer,
    GroupMembershipSerializer,
)

# from groups.api.serializers import GroupSerializer
# from activity.models import Action, ActionOutbox
# from activity.tasks import fanout_action_task
# from activity.models import ActivityType
# from dispatch.api.serializers import PostSerializer
# from dispatch.models import Post
from groups.models import (
    Group,
    GroupInvitation,
    GroupMembership,
)
from groups.permissions import IsGroupAdminOrSteward
from groups.services.groups import GroupService
from groups.services.invitations import InvitationService

# from identity.models import EmblemAvatar  # PHASE 3: Deferred
from users.models import CustomUser
from utils.email.invitations import generate_username_from_email

from ..permissions import IsGroupAdminOrSteward
from .serializers import (
    GroupCreateSerializer,
    GroupDetailSerializer,
    GroupListSerializer,
    GroupMembershipListSerializer,
    GroupMembershipSearchSerializer,
)


User = get_user_model()





class GroupListCreateView(generics.ListCreateAPIView):
    """
    GET /api/groups/ - List all groups user can see
    POST /api/groups/ - Create new group
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return GroupCreateSerializer
        return GroupListSerializer

    def get_queryset(self):
        user = self.request.user

        # Unauthenticated users see only public groups
        if not user.is_authenticated:
            return Group.objects.filter(
                is_active=True,
                visibility="public"
            ).order_by("-created_at")

        # Staff/superuser see all groups
        if user.is_superuser or user.is_staff:
            queryset = Group.objects.filter(is_active=True)
        else:
            # Regular users see public groups + groups they're members of
            user_content_type = ContentType.objects.get_for_model(user)
            member_group_ids = GroupMembership.objects.filter(
                member_content_type=user_content_type,
                member_object_id=user.id,
                is_active=True
            ).values_list("group_id", flat=True)

            queryset = Group.objects.filter(
                is_active=True
            ).filter(
                Q(visibility="public") |
                Q(id__in=member_group_ids)
            ).distinct()

        # Optional filtering
        group_type = self.request.query_params.get("type")
        if group_type:
            queryset = queryset.filter(group_type=group_type)

        return queryset.order_by("-created_at")

    def perform_create(self, serializer):
        """Create group using service layer"""
        user = self.request.user

        # Use service layer to create group
        group = GroupService.create_group(
            title=serializer.validated_data["title"],
            group_type=serializer.validated_data["group_type"],
            created_by=user,
            description=serializer.validated_data.get("description", ""),
            visibility=serializer.validated_data.get("visibility", "public"),
            profile_image=serializer.validated_data.get("profile_image"),
            background_image=serializer.validated_data.get("background_image"),
        )

        return group

    def create(self, request, *args, **kwargs):
        """Override to return detailed group data after creation"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        group = self.perform_create(serializer)

        # Return detailed representation
        detail_serializer = GroupDetailSerializer(
            group,
            context=self.get_serializer_context()
        )
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)


class GroupDetailView(generics.RetrieveUpdateAPIView):
    """
    GET /api/groups/<slug> - Get group details
    PUT/PATCH /api/groups/<slug> - Update group (admin only)
    """
    serializer_class = GroupDetailSerializer
    lookup_field = "slug"
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Group.objects.filter(is_active=True)

    def get_object(self):
        """Override to check view permissions"""
        obj = super().get_object()

        # For read operations, check if user can view
        if self.request.method == "GET":
            if not GroupService.can_user_view_group(obj, self.request.user):
                self.permission_denied(
                    self.request,
                    message="You don't have permission to view this group."
                )

        return obj

    @staticmethod
    @transaction.atomic
    def update_group(group, **fields):
        """
        Update group fields. Supports emblem change via `emblem_id` or `emblem_avatar_id`.
        """
        # 1) Handle emblem change first (either alias)
        emblem_uuid = fields.pop("emblem_avatar_id", None) or fields.pop("emblem_id", None)
        if emblem_uuid is not None:
            group.emblem_id = emblem_uuid  # allow null to clear

        # 2) Whitelist normal updatable fields
        allowed_fields = [
            "title",
            "description",
            "visibility",
            "profile_image",     # raw key (if you still accept it)
            "background_image",  # raw key (if you still accept it)
            # add others you actually allow from the serializer
        ]

        for field, value in fields.items():
            if field in allowed_fields and value is not None:
                setattr(group, field, value)

        group.save()
        return group



class GroupInvitationDetailView(generics.RetrieveAPIView):
    serializer_class = GroupInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        group_slug = self.kwargs["group_slug"]
        return GroupInvitation.objects.filter(group__slug=group_slug)




class GroupMembersView(generics.ListAPIView):
    """
    GET /api/groups/<slug>/members - List group members (flattened GroupMembership[])
    """
    serializer_class = GroupMembershipListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug, is_active=True)

        # Check if user can view members
        if not GroupService.can_user_view_group(group, self.request.user):
            # Return empty queryset instead of 403 for cleaner UX
            return GroupMembership.objects.none()

        # Base queryset - active memberships only
        queryset = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False
        ).select_related("group").prefetch_related("member_object")

        # Optional filtering
        role = self.request.query_params.get("role")
        if role:
            # Map frontend role to backend role
            backend_role = self._map_frontend_role_to_backend(role)
            # Filter by roles array containing the backend role
            queryset = queryset.filter(roles__contains=[backend_role])

        pending = self.request.query_params.get("pending")
        if pending and pending.lower() == "true":
            queryset = queryset.filter(is_pending=True)
        else:
            queryset = queryset.filter(is_pending=False)

        return queryset.order_by("date_joined")

    def _map_frontend_role_to_backend(self, frontend_role):
        """Map frontend role names to backend role names"""
        mapping = {
            "admin": "admin",
            "moderator": "steward",
            "member": "member",
        }
        return mapping.get(frontend_role, frontend_role)







class GroupMemberSearchView(generics.ListAPIView):
    """
    GET /api/groups/<slug>/members/search?q=term - Search group members for autocomplete
    """
    serializer_class = GroupMembershipSearchSerializer
    permission_classes = [permissions.IsAuthenticated, ]

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug, is_active=True)

        search_term = self.request.query_params.get("q", "").strip()
        if not search_term:
            return GroupMembership.objects.none()

        # Search within group members only
        queryset = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            is_pending=False
        ).select_related("group").prefetch_related("member_object")

        # Filter by search term - this will need customization based on your member types
        # For now, assuming User members with standard fields
        if search_term.startswith("@"):
            username_search = search_term[1:]
            # You'll need to implement search across different member types
            # This is a simplified example for User members
            pass

        return queryset[:10]  # Limit for performance


class UserGroupsView(generics.ListAPIView):
    """
    GET /api/groups/my - List groups the current user is a member of
    Moved from /api/user/groups
    """
    serializer_class = GroupListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        user_content_type = ContentType.objects.get_for_model(user)

        # Get groups where user is an active member
        member_group_ids = GroupMembership.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            is_banned=False,
            is_evicted=False
        ).values_list("group_id", flat=True)

        return Group.objects.filter(
            id__in=member_group_ids,
            is_active=True
        ).order_by("title")


class GroupMembersListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupMembershipSerializer
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug)

        qs = GroupMembership.objects.filter(group=group)

        # PHASE 2: Fixed to use correct field names
        role = self.request.query_params.get("role")
        status = self.request.query_params.get("status")

        if role:
            # Use roles__contains to filter by role in the array
            qs = qs.filter(roles__contains=[role])
        if status:
            # Map status to actual boolean fields
            if status == "active":
                qs = qs.filter(is_active=True, is_pending=False, is_banned=False, is_evicted=False)
            elif status == "pending":
                qs = qs.filter(is_pending=True)
            elif status == "banned":
                qs = qs.filter(is_banned=True)
            elif status == "evicted":
                qs = qs.filter(is_evicted=True)

        return qs


class GroupMembershipListView(generics.ListCreateAPIView):
    serializer_class = GroupMembershipSerializer

    def get_queryset(self):
        slug = self.kwargs["slug"]
        return GroupMembership.objects.filter(group__slug=slug)


class GroupInvitationsListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupInvitationSerializer
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug)

        queryset = group.invitations.all()

        # Check for any filters
        status = self.request.query_params.get("status")
        invited_email = self.request.query_params.get("invited_email")

        if status:
            queryset = queryset.filter(status=status)

        if invited_email:
            queryset = queryset.filter(invited_email__icontains=invited_email)

        return queryset


@api_view(["POST"])
@permission_classes([CanInviteMembers])
def invite_to_group(request, slug):
    """
    Invite users to a group.

    Permission: invite_members (via CanInviteMembers - Phase 1 Permission System)
    Allowed roles: admin, steward
    """
    import traceback

    def debug_ts(message: str) -> None:
            print(f"[{dj_timezone.now().isoformat()}] {message}")

    group = get_object_or_404(Group, slug=slug)

    # Permission check is handled by CanInviteMembers decorator
    # which uses Phase 1 PermissionService.can_user_perform_action()

    invited_emails = request.data.get("invited_emails", [])
    invited_usernames = request.data.get("invited_usernames", [])
    message = request.data.get("message", "")

    if not invited_emails and request.data.get("invited_email"):
        invited_emails = [request.data.get("invited_email")]
    if not invited_usernames and request.data.get("invited_username"):
        invited_usernames = [request.data.get("invited_username")]

    if not invited_emails and not invited_usernames:
        return Response(
            {"detail": "Must provide at least one email or username."},
            status=status.HTTP_400_BAD_REQUEST
        )

    invitations_created = []
    errors = []

    # Process usernames
    for username in invited_usernames:
        try:
            user = CustomUser.objects.get(username=username, is_active=True)
            invitation, is_existing_user = InvitationService.create_invitation(group, user, user.email, request.user, message)
            invitations_created.append((invitation, is_existing_user))
        except CustomUser.DoesNotExist:
            errors.append({"username": username, "error": "User not found"})
        except ValidationError as e:
            errors.append({"username": username, "error": str(e)})
        except Exception as e:
            debug_ts(print(f"[ERROR] create_invitation failed for username {username}: {e}"))
            traceback.print_exc()
            errors.append({"username": username, "error": str(e)})

    # Process emails
    for email in invited_emails:
        try:
            user, _ = CustomUser.objects.get_or_create(
                email=email,
                defaults={
                    "username": generate_username_from_email(email),
                    "is_active": False,
                },
            )
            debug_ts(f"[DEBUG] About to call create_invitation for {email}")
            invitation, is_existing_user = InvitationService.create_invitation(group, user, email, request.user, message)
            debug_ts(f"[DEBUG] create_invitation succeeded for {email}")

            invitations_created.append((invitation, is_existing_user))
        except Exception as e:
            print(f"[ERROR] create_invitation failed for email {email}: {type(e).__name__}: {e}")
            traceback.print_exc()
            errors.append({"email": email, "error": str(e)})

    debug_ts(f"[DEBUG] Invitations created: {len(invitations_created)}, Errors: {len(errors)}")
    debug_ts("[DEBUG] About to call send_batch_invitations")

    # Batch send emails via Celery
    if invitations_created:
        try:
            debug_ts(f"[DEBUG] Calling InvitationService.send_batch_invitations with {len(invitations_created)} invitations")
            InvitationService.send_batch_invitations(invitations_created, group, request.user, message)
            debug_ts("[DEBUG] send_batch_invitations completed successfully")
        except Exception as e:
            debug_ts(f"[ERROR] send_batch_invitations failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            errors.append({"batch_error": str(e)})

    response_data = {
        "invitations_created": len(invitations_created),
        "invitations": [{"id": inv[0].id, "email": inv[0].invited_email} for inv in invitations_created],
    }

    if errors:
        response_data["errors"] = errors
        response_data["detail"] = f"Created {len(invitations_created)} invitations with {len(errors)} errors"
        return Response(response_data, status=status.HTTP_207_MULTI_STATUS)

    return Response(response_data, status=status.HTTP_201_CREATED)




@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def accept_invite(request):
    """
    Unified endpoint for accepting group invitations.
    Handles both new users (ghost -> active) and existing users joining new groups.

    POST /api/invitations/accept

    Request body:
    {
        "shortcode": "abc123",
        "password": "..." (required for new users),
        "username": "..." (required for new users)
    }
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    shortcode = data.get("shortcode")
    if not shortcode:
        return JsonResponse({"error": "Missing shortcode."}, status=400)

    # Extract optional fields for new user activation
    password = data.get("password")
    username = data.get("username")

    # Use service layer to process the invitation
    try:
        result = InvitationService.accept_invite_by_shortcode(
            shortcode=shortcode,
            password=password,
            username=username,
            authenticated_user=request.user
        )

        # Return success response
        return JsonResponse({
            "detail": "Successfully joined group.",
            "user_was_new": result["user_was_new"],
            "group": {
                "id": str(result["group"].id),
                "title": result["group"].title,
                "slug": result["group"].slug,
            }
        }, status=200)

    except ValidationError as e:
        # Service layer raises ValidationError with specific messages
        return JsonResponse({"error": str(e)}, status=400)

    except Exception:
        # Catch any unexpected errors
        return JsonResponse(
            {"error": "An unexpected error occurred."},
            status=500
        )

