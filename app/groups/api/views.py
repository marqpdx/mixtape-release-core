# groups/api/views.py

import json
import uuid

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
    GroupOverviewLayoutSerializer,
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
    GroupOverviewLayout,
)
from groups.models.group import InvitationKind, InvitationStatus
from groups.permissions import IsGroupAdminOrSteward, canUserModerateGroupUser
from groups.services.groups import GroupService
from identity.models import EmblemAvatar
from groups.services.invitations import InvitationService

# from identity.models import EmblemAvatar  # PHASE 3: Deferred
from users.models import CustomUser
from utils.email.invitations import generate_username_from_email
from mixtape.services.defaults import get_default_group
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.models import WritingPiece

from ..permissions import HasGroupDecorator, IsGroupAdminOrSteward
from .serializers import (
    GroupCreateSerializer,
    GroupDetailSerializer,
    GroupListSerializer,
    GroupMembershipListSerializer,
    GroupMembershipSearchSerializer,
)

DEFAULT_OVERVIEW_BLOCKS = [
    {"type": "welcome", "width": "two_thirds", "visibility": "members", "config": {}},
    {"type": "member_highlights", "width": "one_third", "visibility": "members", "config": {}},
    {"type": "announcements", "width": "two_thirds", "visibility": "members", "config": {}},
    {"type": "upcoming_events", "width": "one_third", "visibility": "members", "config": {}},
    {"type": "pinned_writing", "width": "two_thirds", "visibility": "members", "config": {}},
    {"type": "recent_posts", "width": "two_thirds", "visibility": "members", "config": {}},
    {"type": "pinned_resources", "width": "full", "visibility": "members", "config": {}},
    {"type": "stewards", "width": "one_third", "visibility": "members", "config": {}},
]


def build_default_overview_blocks():
    blocks = []
    for block in DEFAULT_OVERVIEW_BLOCKS:
        entry = dict(block)
        entry["id"] = str(uuid.uuid4())
        blocks.append(entry)
    return blocks


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
            user_content_type = ContentType.objects.get_for_model(User)
            member_group_ids = GroupMembership.objects.filter(
                member_content_type=user_content_type,
                member_object_id=user.pk,
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

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(slug__icontains=search) |
                Q(description__icontains=search)
            )

        exclude = self.request.query_params.getlist("exclude")
        if exclude:
            if "unlisted" in exclude:
                queryset = queryset.exclude(visibility="unlisted")
            if "private" in exclude:
                queryset = queryset.exclude(visibility="private")

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
            summary=serializer.validated_data.get("summary", ""),
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


class GroupWelcomePinView(generics.GenericAPIView):
    """
    GET /api/groups/<slug>/welcome
    Returns the most relevant welcome pin for the current user.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        if not GroupService.can_user_view_group(group, request.user):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        ct_group = ContentType.objects.get_for_model(Group)
        ct_piece = ContentType.objects.get_for_model(WritingPiece)

        placements = (
            ContentPlacement.objects.filter(
                target_content_type=ct_group,
                target_object_id=group.id,
                source_content_type=ct_piece,
                channel="feed",
                overrides__pin_kind="welcome",
            )
            .order_by("-created_at")
        )

        if not placements.exists():
            return Response(status=status.HTTP_204_NO_CONTENT)

        user = request.user if request.user.is_authenticated else None
        is_group_member = bool(user and GroupService.get_user_membership(group, user))

        default_group = get_default_group()
        is_default_member = bool(
            user and default_group and GroupService.get_user_membership(default_group, user)
        )

        if is_group_member:
            allowed_audiences = ["group", "community", "public"]
        elif is_default_member:
            allowed_audiences = ["community", "public"]
        else:
            allowed_audiences = ["public"]

        for audience in allowed_audiences:
            for placement in placements:
                overrides = placement.overrides or {}
                placement_audience = overrides.get("pin_audience") or "group"
                if placement_audience != audience:
                    continue
                if not can_view_placement(placement, user):
                    continue
                try:
                    payload = get_display_payload(placement)
                except Exception:
                    continue

                piece = payload.get("source")
                if not piece or getattr(piece, "status", None) != "published":
                    continue

                metadata = payload.get("metadata") or {}
                author_name = getattr(piece, "author_name", None)
                if not author_name and getattr(piece, "author", None):
                    author_name = piece.author.get_full_name() or piece.author.username

                return Response(
                    {
                        "placement_id": str(placement.id),
                        "audience": placement_audience,
                        "piece": {
                            "id": str(piece.id),
                            "slug": piece.slug,
                            "title": metadata.get("title") or piece.title,
                            "excerpt": metadata.get("excerpt") or piece.excerpt,
                            "published_at": piece.published_at,
                            "author_name": author_name,
                        },
                        "display": {
                            "title": metadata.get("title"),
                            "excerpt": metadata.get("excerpt"),
                        },
                    }
                )


class DefaultGroupView(generics.GenericAPIView):
    """
    GET /api/groups/default
    Returns the default group (by settings), if present.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        default_group = get_default_group()
        if not default_group:
            return Response({"detail": "Default group not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(
            {
                "id": str(default_group.id),
                "slug": default_group.slug,
                "title": default_group.title,
                "group_type": getattr(default_group, "group_type", None),
            }
        )

        return Response(status=status.HTTP_204_NO_CONTENT)


class GroupEmblemAttachView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/emblem/attach
    Body: { "emblem_id": "<uuid>" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not (membership.is_admin() or membership.is_steward()):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        emblem_id = request.data.get("emblem_id")
        if not emblem_id:
            return Response({"detail": "emblem_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        emblem = get_object_or_404(EmblemAvatar, id=emblem_id)
        if not emblem.can_be_attached_by(request.user):
            return Response({"detail": "Emblem cannot be attached by this user."}, status=status.HTTP_403_FORBIDDEN)

        group.emblem = emblem
        group.save(update_fields=["emblem"])
        return Response(GroupDetailSerializer(group, context={"request": request}).data)


class GroupEmblemResetView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/emblem/reset
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not (membership.is_admin() or membership.is_steward()):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        group.emblem = None
        group.save(update_fields=["emblem"])
        return Response(GroupDetailSerializer(group, context={"request": request}).data)


class GroupOverviewLayoutView(generics.RetrieveUpdateAPIView):
    """
    GET/PUT /api/groups/<slug>/overview-layout
    """
    serializer_class = GroupOverviewLayoutSerializer
    permission_classes = [permissions.AllowAny]

    def _get_group(self):
        return get_object_or_404(Group, slug=self.kwargs["slug"], is_active=True)

    def _ensure_layout(self, group):
        layout = getattr(group, "overview_layout", None)
        if layout:
            return layout
        return GroupOverviewLayout.objects.create(
            group=group,
            layout_version="1",
            blocks=build_default_overview_blocks(),
        )

    def get_object(self):
        group = self._get_group()
        if self.request.method == "GET":
            if not GroupService.can_user_view_group(group, self.request.user):
                self.permission_denied(self.request, message="You don't have permission to view this group.")
        return self._ensure_layout(group)

    def update(self, request, *args, **kwargs):
        group = self._get_group()
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not (membership.is_admin() or membership.is_steward()):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)


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



# # groups/api/views/circles.py

# from django.contrib.contenttypes.models import ContentType
# from django.db.models import Q
# from rest_framework import generics, permissions, status
# from rest_framework.response import Response

# from groups.models import Group
# from groups.models.dec_enums import GroupType
# from groups.api.serializers.groups import GroupCreateSerializer, GroupListSerializer, GroupDetailSerializer
# from groups.permissions.decorators import HasGroupDecorator  # your existing permission
# from groups.services.groups import GroupService


class GroupCirclesListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/groups/<group_slug>/circles
      - List circles sponsored by this group.

    POST /api/groups/<group_slug>/circles
      - Create a new circle sponsored by this group.
      - Requires the user to have can__CreateSponsoredCircle on their membership
        within the sponsoring group.
    """
    permission_classes = [permissions.IsAuthenticated, HasGroupDecorator]
    required_decorator = "can__CreateSponsoredCircle"

    # If your HasGroupDecorator needs to know what group to scope to,
    # it commonly looks for this kwarg name:
    sponsor_slug_kwarg = "slug"

    def get_sponsor_group(self) -> Group:
        sponsor_slug = self.kwargs.get("slug")
        return Group.objects.get(slug=sponsor_slug, is_active=True)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return GroupCreateSerializer
        return GroupListSerializer

    def get_queryset(self):
        sponsor_group = self.get_sponsor_group()
        sponsor_ct = ContentType.objects.get_for_model(Group)

        qs = Group.objects.filter(
            is_active=True,
            group_type='circle',
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=sponsor_group.id,
        ).order_by("-created_at")

        # Optional filters, if you want parity with /api/groups/
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search)
            )

        return qs

    def create(self, request, *args, **kwargs):
        """
        Override to return GroupDetailSerializer after creation,
        matching your main GroupListCreateView behavior.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        circle = self.perform_create(serializer)

        detail = GroupDetailSerializer(circle, context=self.get_serializer_context())
        return Response(detail.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        sponsor_group = self.get_sponsor_group()

        # IMPORTANT: Force these server-side so the client can’t spoof them
        validated = dict(serializer.validated_data)
        # validated["group_type"] = GroupType.CIRCLE

        validated["group_type"] = 'circle'

        # If you store circle fields on GroupCreateSerializer already, great.
        # If not, you'll add start_date/end_date/join_mode/etc to serializer Meta.fields.

        # Create the circle *sponsored by the group*
        # You have two options:
        #
        # A) If you have or add a helper in GroupService:
        #    circle = GroupService.create_group_sponsored_by_group(...)
        #
        # B) Or create then set sponsor manually (shown here):

        circle = GroupService.create_group(
            title=validated["title"],
            group_type=validated["group_type"],
            created_by=self.request.user,
            description=validated.get("description", ""),
            visibility=validated.get("visibility", "public"),
            profile_image=validated.get("profile_image_path"),
            background_image=validated.get("background_image_path"),
            sponsor=sponsor_group,
            add_creator_membership=True,
        )

        # If you have Circle-specific detail fields on CircleGroup, set them here
        # (only if you’re not storing these on Group directly)
        #
        # Example:
        # if hasattr(circle, "circle_detail"):
        #     circle.circle_detail.start_date = validated.get("start_date")
        #     circle.circle_detail.end_date = validated.get("end_date")
        #     circle.circle_detail.save()

        return circle


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
        user_content_type = ContentType.objects.get_for_model(User)

        # Get groups where user is an active member
        member_group_ids = GroupMembership.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.pk,
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


class GroupCoalitionInvitationsListView(generics.ListAPIView):
    """
    List coalition invitations/requests for a coalition group.
    """
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupInvitationSerializer
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug)

        if group.group_type != "coalition":
            return GroupInvitation.objects.none()

        queryset = group.invitations.filter(invited_group__isnull=False)

        status_filter = self.request.query_params.get("status")
        kind_filter = self.request.query_params.get("kind")

        if status_filter:
            queryset = queryset.filter(invitation_status=status_filter)
        if kind_filter:
            queryset = queryset.filter(invitation_kind=kind_filter)

        return queryset


class GroupCoalitionInvitationsReceivedListView(generics.ListAPIView):
    """
    List coalition invitations/requests received by a group.
    """
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupInvitationSerializer
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug)

        queryset = GroupInvitation.objects.filter(invited_group=group)

        status_filter = self.request.query_params.get("status")
        kind_filter = self.request.query_params.get("kind")

        if status_filter:
            queryset = queryset.filter(invitation_status=status_filter)
        if kind_filter:
            queryset = queryset.filter(invitation_kind=kind_filter)

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
@permission_classes([permissions.IsAuthenticated, IsGroupAdminOrSteward])
def invite_group_to_coalition(request, slug):
    """
    Invite a group to join a coalition.
    """
    coalition = get_object_or_404(Group, slug=slug)
    if coalition.group_type != "coalition":
        return Response(
            {"detail": "Group is not a coalition."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    invited_group_slug = request.data.get("invited_group_slug")
    message = request.data.get("message", "")

    if not invited_group_slug:
        return Response(
            {"detail": "invited_group_slug is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    invited_group = get_object_or_404(Group, slug=invited_group_slug)
    if invited_group.visibility == "unlisted":
        return Response(
            {"detail": "Unlisted groups cannot be invited to a coalition."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        invitation = InvitationService.create_group_invitation(
            coalition=coalition,
            invited_group=invited_group,
            invited_by=request.user,
            message=message,
            kind=InvitationKind.INVITE,
        )
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {"id": invitation.id, "detail": "Invitation created."},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def request_to_join_coalition(request, slug):
    """
    Request to join a coalition as a group.
    """
    coalition = get_object_or_404(Group, slug=slug)
    if coalition.group_type != "coalition":
        return Response(
            {"detail": "Group is not a coalition."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    requesting_group_slug = request.data.get("requesting_group_slug")
    message = request.data.get("message", "")

    if not requesting_group_slug:
        return Response(
            {"detail": "requesting_group_slug is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    requesting_group = get_object_or_404(Group, slug=requesting_group_slug)

    if not canUserModerateGroupUser(request.user, requesting_group):
        return Response(
            {"detail": "You do not have permission to request for this group."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invitation = InvitationService.create_group_invitation(
            coalition=coalition,
            invited_group=requesting_group,
            invited_by=request.user,
            message=message,
            kind=InvitationKind.REQUEST,
        )
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {"id": invitation.id, "detail": "Join request created."},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def respond_to_group_invitation(request, invitation_id):
    """
    Accept or decline a group-to-group invitation/request.
    """
    invitation = get_object_or_404(GroupInvitation, pk=invitation_id)
    action = request.data.get("action")

    try:
        InvitationService.respond_to_group_invitation(invitation, request.user, action)
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    detail = "Invitation accepted." if action == "accept" else "Invitation declined."
    return Response({"detail": detail}, status=status.HTTP_200_OK)


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

    data = request.data
    if not isinstance(data, dict):
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
