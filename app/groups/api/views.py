# groups/api/views.py

import datetime as dt
import json
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

# from utils.email.shortcode import generate_shortcode
# from utils.tasks import send_transactional_email_task
# ============================================================================
# PHASE 3+: Writing Integration (Deferred)
# ============================================================================
# from writing.api.serializers import WritingPieceSerializer, WritingPlacementSerializer, WorkingDocumentSerializer
# from writing.models import WritingPiece, WritingPlacement, WorkingDocument
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from accounts.api.throttles import InviteThrottle
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

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
from groups.models.group_context import GroupContext
from groups.models.group import InvitationKind, InvitationStatus, InviteLink
from groups.permissions import IsGroupAdminOrSteward, canUserModerateGroupUser
from groups.services.groups import GroupService
from identity.models import EmblemAvatar
from groups.services.invitations import InvitationService
from groups.services.memberships import ensure_user_membership

# from identity.models import EmblemAvatar  # PHASE 3: Deferred
from users.models import CustomUser
from utils.email.invitations import generate_username_from_email
from mixtape.services.defaults import get_default_group
from mixtape.tenant_urls import get_catalyst_workspace_url
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
        if not request.user or not request.user.is_superuser:
            raise PermissionDenied("Group creation is restricted.")
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

    # Fields that map to live PublicPage slots (CR-01A)
    _PAGE_SLOT_FIELDS = {"title", "description", "profile_image", "background_image"}

    def partial_update(self, request, *args, **kwargs):
        """
        CR-01A: if the group has a published PublicPage and the PATCH touches a
        live slot field, intercept and return a confirmation flag before saving.
        The caller must re-PATCH with `confirm_public_update: true` to proceed.
        """
        from groups.models.public_page import PublicPage

        group = self.get_object()
        touched = set(request.data.keys()) & self._PAGE_SLOT_FIELDS

        if touched and not request.data.get("confirm_public_update"):
            try:
                page = group.public_page
                if page.status == PublicPage.Status.PUBLISHED:
                    return Response(
                        {
                            "public_page_confirmation_required": True,
                            "affected_slots": sorted(touched),
                            "detail": (
                                "One or more fields you are editing are live on your "
                                "public Crossroads Page. Re-submit with "
                                "'confirm_public_update: true' to save."
                            ),
                        },
                        status=status.HTTP_200_OK,
                    )
            except PublicPage.DoesNotExist:
                pass

        return super().partial_update(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        if not request.user or not request.user.is_superuser:
            raise PermissionDenied("You don't have permission to delete groups.")

        group = self.get_object()
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
            "admission_policy",
            "profile_image",     # raw key (if you still accept it)
            "background_image",  # raw key (if you still accept it)
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
                            "body_json": metadata.get("body_json") or piece.body_json,
                            "published_at": piece.published_at,
                            "author_name": author_name,
                        },
                        "display": {
                            "title": metadata.get("title"),
                            "excerpt": metadata.get("excerpt"),
                            "body_json": metadata.get("body_json"),
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
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

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


class GroupContextView(generics.GenericAPIView):
    """
    GET  /api/groups/<slug>/context  — return the group's AI context fields
    PATCH /api/groups/<slug>/context  — update them (admin/steward only)
    """
    permission_classes = [permissions.IsAuthenticated]

    WRITABLE_FIELDS = ("founding_story", "non_negotiables", "voice_description", "outward_feel")

    def _get_group(self):
        return get_object_or_404(Group, slug=self.kwargs["slug"], is_active=True)

    def _serialize(self, ctx):
        return {
            "founding_story": ctx.founding_story,
            "non_negotiables": ctx.non_negotiables,
            "voice_description": ctx.voice_description,
            "outward_feel": ctx.outward_feel,
            "context_health_score": ctx.context_health_score,
            "updated_at": ctx.updated_at.isoformat() if ctx.updated_at else None,
            "dispatch_policy": ctx.group.dispatch_policy,
            "local_model_tier": ctx.group.local_model_tier,
            "local_verb_overrides": ctx.group.local_verb_overrides,
        }

    def get(self, request, slug):
        group = self._get_group()
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_active:
            return Response({"detail": "Not a member."}, status=status.HTTP_403_FORBIDDEN)
        ctx, _ = GroupContext.objects.get_or_create(group=group)
        return Response(self._serialize(ctx))

    def patch(self, request, slug):
        group = self._get_group()
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not (membership.is_admin() or membership.is_steward()):
            return Response({"detail": "Admin or steward required."}, status=status.HTTP_403_FORBIDDEN)
        ctx, _ = GroupContext.objects.get_or_create(group=group)
        for field in self.WRITABLE_FIELDS:
            if field in request.data:
                setattr(ctx, field, request.data[field])
        ctx.save()
        return Response(self._serialize(ctx))


class GroupInvitationDetailView(generics.RetrieveDestroyAPIView):
    serializer_class = GroupInvitationSerializer
    permission_classes = [permissions.IsAuthenticated, CanInviteMembers]
    lookup_field = "pk"

    def get_queryset(self):
        group_slug = self.kwargs["group_slug"]
        return GroupInvitation.objects.filter(group__slug=group_slug)

    def destroy(self, request, *args, **kwargs):
        invitation = self.get_object()
        if invitation.invitation_status == "joined":
            return Response(
                {"error": "Cannot delete an invitation that has already been accepted"},
                status=status.HTTP_400_BAD_REQUEST
            )
        invitation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
    GET  /api/groups/<slug>/circles  — list Circles parented to this group.
    POST /api/groups/<slug>/circles  — create a Circle; caller must be admin of parent (D2).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_parent_group(self) -> Group:
        return get_object_or_404(Group, slug=self.kwargs["slug"], is_active=True)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return GroupCreateSerializer
        return GroupListSerializer

    def get_queryset(self):
        parent = self.get_parent_group()
        qs = Group.objects.filter(
            is_active=True,
            group_type="circle",
            parent=parent,
        ).order_by("-created_at")
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(description__icontains=search)
            )
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        parent = self.get_parent_group()
        try:
            circle = GroupService.create_circle(
                parent=parent,
                title=validated["title"],
                created_by=request.user,
                description=validated.get("description", ""),
                visible_to_parent=validated.get("visible_to_parent", True),
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        detail = GroupDetailSerializer(circle, context=self.get_serializer_context())
        return Response(detail.data, status=status.HTTP_201_CREATED)


class GroupCircleDetailView(generics.RetrieveAPIView):
    """
    GET /api/groups/<parent_slug>/circles/<circle_slug>
    Returns the Circle, validating it is parented to the given group.
    """
    serializer_class = GroupDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_object(self):
        parent = get_object_or_404(Group, slug=self.kwargs["parent_slug"], is_active=True)
        circle = get_object_or_404(
            Group,
            slug=self.kwargs["circle_slug"],
            is_active=True,
            group_type="circle",
            parent=parent,
        )
        if not GroupService.can_user_view_group(circle, self.request.user):
            self.permission_denied(
                self.request,
                message="You don't have permission to view this circle.",
            )
        return circle


def _delete_who_we_are_post(group, user_id):
    """Delete a user's intro post(s) from the group's Who We Are discussion on removal."""
    from threadworks.models import Post
    group_ct = ContentType.objects.get_for_model(group.__class__)
    Post.objects.filter(
        discussion__slug="who-we-are",
        discussion__forum__sponsor_content_type=group_ct,
        discussion__forum__sponsor_object_id=group.id,
        discussion__forum__title="Welcome",
        author_id=user_id,
    ).delete()


class GroupMemberRemoveView(generics.GenericAPIView):
    """
    DELETE /api/groups/<slug>/members/<uuid:membership_id>
    Remove a member from a group (soft-delete: sets is_evicted=True, is_active=False).
    Requires admin or steward role in the group.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, slug, membership_id):
        group = get_object_or_404(Group, slug=slug, is_active=True)

        # Check requesting user is admin or steward
        requester_membership = GroupService.get_user_membership(group, request.user)
        if not requester_membership or not (requester_membership.is_admin() or requester_membership.is_steward()):
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        # Find the target membership by member_object_id (user UUID)
        target_membership = get_object_or_404(
            GroupMembership,
            group=group,
            member_object_id=membership_id,
            is_active=True,
        )

        # Prevent removing owners
        if target_membership.is_owner():
            return Response(
                {"detail": "Cannot remove the group owner."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Stewards cannot remove admins
        if target_membership.is_admin() and not requester_membership.is_admin():
            return Response(
                {"detail": "Only admins can remove other admins."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Prevent removing yourself
        user_ct = ContentType.objects.get_for_model(User)
        if (
            target_membership.member_content_type == user_ct
            and target_membership.member_object_id == request.user.id
        ):
            return Response(
                {"detail": "Cannot remove yourself from the group."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Soft-delete: mark as evicted and inactive
        target_membership.is_evicted = True
        target_membership.is_active = False
        target_membership.save(update_fields=["is_evicted", "is_active"])

        # Remove any open group invitations for this user
        GroupInvitation.objects.filter(
            group=group,
            invited_user_id=target_membership.member_object_id,
        ).delete()

        # Remove member's introduction from the Who We Are discussion
        _delete_who_we_are_post(group, target_membership.member_object_id)

        return Response(status=status.HTTP_204_NO_CONTENT)


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
    permission_classes = [permissions.IsAuthenticated, CanInviteMembers]
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
    silent_add_raw = request.data.get("silent_add", False)
    silent_add = str(silent_add_raw).lower() in {"1", "true", "yes", "on"}

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
    memberships_added = []
    errors = []

    # Process usernames
    if silent_add:
        # Silent mode applies only to @username entries. Email invites still run normally below.
        for username in invited_usernames:
            try:
                user = CustomUser.objects.get(username=username, is_active=True)
                membership = ensure_user_membership(group, user, role="member", is_active=True)
                memberships_added.append(
                    {
                        "user_id": str(user.id),
                        "username": user.username,
                        "membership_id": str(membership.id),
                    }
                )
            except CustomUser.DoesNotExist:
                errors.append({"username": username, "error": "Active user not found"})
            except Exception as e:
                errors.append({"username": username, "error": str(e)})
    else:
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
        "silent_add": silent_add,
        "memberships_added": len(memberships_added),
        "members": memberships_added,
        "invitations_created": len(invitations_created),
        "invitations": [{"id": inv[0].id, "email": inv[0].invited_email} for inv in invitations_created],
    }

    if errors:
        response_data["errors"] = errors
        response_data["detail"] = (
            f"Added {len(memberships_added)} member(s), created {len(invitations_created)} invitation(s), "
            f"with {len(errors)} error(s)"
        )
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
@throttle_classes([InviteThrottle])
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
        grp = result["group"]
        response_data = {
            "success": True,
            "detail": "Successfully joined group.",
            "user_was_new": result["user_was_new"],
            "group": {
                "id": str(grp.id),
                "title": grp.title,
                "slug": grp.slug,
                "profile_image_url": grp.profile_image_url,
            }
        }

        if result["user_was_new"]:
            refresh = RefreshToken.for_user(result["user"])
            access = refresh.access_token
            access["username"] = result["user"].username
            response_data.update({
                "refresh": str(refresh),
                "refresh_expires": refresh["exp"],
                "access": str(access),
                "access_expires": access["exp"],
                "user": {
                    "id": str(result["user"].id),
                    "username": result["user"].username,
                    "email": result["user"].email,
                },
            })

        resp = JsonResponse(response_data, status=200)

        if result["user_was_new"]:
            expiration = dt.datetime.utcnow() + jwt_settings.REFRESH_TOKEN_LIFETIME
            resp.set_cookie(
                settings.JWT_COOKIE_NAME,
                response_data["refresh"],
                expires=expiration,
                secure=settings.JWT_COOKIE_SECURE,
                httponly=True,
                samesite=settings.JWT_COOKIE_SAMESITE,
                path="/",
                domain=getattr(settings, "SESSION_COOKIE_DOMAIN", None),
            )

        return resp

    except ValidationError as e:
        # Service layer raises ValidationError with specific messages
        return JsonResponse({"error": str(e)}, status=400)

    except Exception:
        # Catch any unexpected errors
        return JsonResponse(
            {"error": "An unexpected error occurred."},
            status=500
        )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
@throttle_classes([InviteThrottle])
def invite_info(request, shortcode):
    """
    Return public group info for an invite link shortcode.
    Used by the accept-invite page to render the group name and image before submission.

    GET /api/auth/invite-info/{shortcode}
    """
    try:
        invite = InviteLink.objects.select_related("group").get(shortcode=shortcode)
    except InviteLink.DoesNotExist:
        return JsonResponse({"error": "Invalid or expired invite link."}, status=404)

    if invite.is_used:
        return JsonResponse({"error": "This invitation has already been used."}, status=410)

    grp = invite.group
    return JsonResponse({
        "is_existing_user": bool(invite.user and invite.user.is_active),
        "group": {
            "title": grp.title,
            "slug": grp.slug,
            "profile_image_url": grp.profile_image_url,
        }
    }, status=200)


# ============================================================================
# User Join / Request-to-Join
# ============================================================================

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def join_group(request, slug):
    """
    POST /api/groups/{slug}/join

    User directly joins a group (for OPEN / OPEN_PARENT_MEMBERS policies).
    """
    from groups.services.join_service import join_group as join_group_service

    group = get_object_or_404(Group, slug=slug, is_active=True)

    try:
        membership = join_group_service(group, request.user)
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "detail": "Successfully joined group.",
            "group": {"id": str(group.id), "title": group.title, "slug": group.slug},
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def request_to_join_group(request, slug):
    """
    POST /api/groups/{slug}/request-join

    User submits a join request (for APPLICATION / APPLICATION_PARENT_MEMBERS policies).
    """
    from groups.services.join_service import request_to_join_group as request_join_service

    group = get_object_or_404(Group, slug=slug, is_active=True)
    message = request.data.get("message", "")

    try:
        invitation = request_join_service(group, request.user, message=message)
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "detail": "Join request submitted.",
            "invitation_id": invitation.id,
            "group": {"id": str(group.id), "title": group.title, "slug": group.slug},
        },
        status=status.HTTP_201_CREATED,
    )


class GroupJoinRequestsListView(generics.ListAPIView):
    """
    GET /api/groups/{slug}/join-requests

    List pending join requests for a group. Admin/steward only.
    """
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupInvitationSerializer

    def get_queryset(self):
        slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=slug)
        return GroupInvitation.objects.filter(
            group=group,
            invitation_kind=InvitationKind.REQUEST,
            invited_user__isnull=False,
            invitation_status=InvitationStatus.PENDING,
        ).select_related("invited_user", "group").order_by("-created_at")


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated, IsGroupAdminOrSteward])
def respond_to_join_request(request, slug, invitation_id):
    """
    POST /api/groups/{slug}/join-requests/{invitation_id}/respond

    Accept or decline a user's join request. Admin/steward only.
    """
    from groups.services.join_service import respond_to_join_request as respond_service

    group = get_object_or_404(Group, slug=slug, is_active=True)
    invitation = get_object_or_404(
        GroupInvitation,
        pk=invitation_id,
        group=group,
        invitation_kind=InvitationKind.REQUEST,
        invited_user__isnull=False,
    )
    action = request.data.get("action")

    if action not in ("accept", "decline"):
        return Response(
            {"detail": "action must be 'accept' or 'decline'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        respond_service(invitation, request.user, action)
    except ValidationError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    detail = "Join request accepted." if action == "accept" else "Join request declined."
    return Response({"detail": detail}, status=status.HTTP_200_OK)


# ============================================================================
# Group Announcements (Noticeboard)
# ============================================================================

class GroupAnnouncementListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/groups/<slug>/announcements/         — admin/steward: full list
    POST /api/groups/<slug>/announcements/         — admin/steward: create

    Members see the visible queue via GroupAnnouncementVisibleQueueView.
    """

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [permissions.IsAuthenticated(), IsGroupAdminOrSteward()]
        return [permissions.IsAuthenticated(), IsGroupAdminOrSteward()]

    def _get_group(self):
        return get_object_or_404(Group, slug=self.kwargs["group_slug"], is_active=True)

    def get_serializer_class(self):
        from groups.api.serializers import GroupAnnouncementSerializer
        return GroupAnnouncementSerializer

    def get_queryset(self):
        from groups.models import GroupAnnouncement
        group = self._get_group()
        return GroupAnnouncement.objects.filter(group=group).select_related("author").order_by(
            "priority", "position", "-created_at"
        )

    def perform_create(self, serializer):
        from groups.models import GroupAnnouncement
        from django.utils import timezone
        group = self._get_group()
        instance = serializer.save(group=group, author=self.request.user)
        if instance.also_send_notification:
            from activity.producers import on_group_announcement
            on_group_announcement(group=group, announcement=instance, authored_by=self.request.user)
            GroupAnnouncement.objects.filter(pk=instance.pk).update(notification_sent_at=timezone.now())


class GroupAnnouncementDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/groups/<slug>/announcements/<pk>/  — admin/steward
    PATCH  /api/groups/<slug>/announcements/<pk>/  — admin/steward: edit
    DELETE /api/groups/<slug>/announcements/<pk>/  — admin/steward: remove
    """
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]

    def get_serializer_class(self):
        from groups.api.serializers import GroupAnnouncementSerializer
        return GroupAnnouncementSerializer

    def get_object(self):
        from groups.models import GroupAnnouncement
        group = get_object_or_404(Group, slug=self.kwargs["group_slug"], is_active=True)
        return get_object_or_404(GroupAnnouncement, pk=self.kwargs["pk"], group=group)


class GroupAnnouncementVisibleQueueView(generics.ListAPIView):
    """
    GET /api/groups/<slug>/announcements/visible-queue/

    Member-facing: returns announcements visible to this user (active,
    not expired, not permanently dismissed, snooze window respected).
    Sorted by priority then position.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        from groups.api.serializers import GroupAnnouncementSerializer
        return GroupAnnouncementSerializer

    def get_queryset(self):
        from groups.models import GroupAnnouncement
        group = get_object_or_404(Group, slug=self.kwargs["group_slug"], is_active=True)
        visible = GroupAnnouncement.get_visible_queue_for_user(group, self.request.user)
        # Return as queryset-like list — ListAPIView accepts iterables
        return visible

    def list(self, request, *args, **kwargs):
        from groups.api.serializers import GroupAnnouncementSerializer
        items = self.get_queryset()
        serializer = GroupAnnouncementSerializer(items, many=True)
        return Response(serializer.data)


class GroupAnnouncementDismissView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/announcements/<pk>/dismiss/

    First call  → snooze 48 hrs
    Second call → permanent dismissal
    Returns { "result": "snooze"|"permanent", "snoozed_until": "<iso>"|null }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, group_slug, pk):
        from groups.models import GroupAnnouncement, AnnouncementDismissal
        group = get_object_or_404(Group, slug=group_slug, is_active=True)
        announcement = get_object_or_404(GroupAnnouncement, pk=pk, group=group, is_active=True)
        result, snoozed_until = AnnouncementDismissal.dismiss_announcement(announcement, request.user)
        return Response({
            "result": result,
            "snoozed_until": snoozed_until.isoformat() if snoozed_until else None,
        })


class GroupAnnouncementCreateFromContentView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/announcements/create-from-content/

    Wraps an existing content object (course, event, post, etc.) into
    an announcement. Resolves source via content_type model name + content_id.
    """
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]

    def get_serializer_class(self):
        from groups.api.serializers import CreateAnnouncementFromContentSerializer
        return CreateAnnouncementFromContentSerializer

    def post(self, request, group_slug):
        from groups.models import GroupAnnouncement
        from groups.api.serializers import CreateAnnouncementFromContentSerializer, GroupAnnouncementSerializer
        from django.utils import timezone

        group = get_object_or_404(Group, slug=group_slug, is_active=True)
        serializer = CreateAnnouncementFromContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_ct = ContentType.objects.get(model=data["content_type"])
        source_obj = source_ct.get_object_for_this_type(pk=data["content_id"])

        announcement = GroupAnnouncement.objects.create(
            group=group,
            author=request.user,
            title=data["title"],
            content=data["content"],
            priority=data.get("priority", "normal"),
            cta_text=data.get("cta_text", ""),
            cta_url=data.get("cta_url", ""),
            expires_at=data.get("expires_at"),
            also_send_notification=data.get("also_send_notification", False),
            source_content_type=source_ct,
            source_object_id=source_obj.pk,
        )

        if announcement.also_send_notification:
            from activity.producers import on_group_announcement
            on_group_announcement(group=group, announcement=announcement, authored_by=request.user)
            GroupAnnouncement.objects.filter(pk=announcement.pk).update(notification_sent_at=timezone.now())

        return Response(GroupAnnouncementSerializer(announcement).data, status=status.HTTP_201_CREATED)


class GroupCatalystIntakeView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/catalyst-intake

    Lets an existing group's owner or admin request Catalyst activation from
    within the Group Work Area. Creates a BusinessProspect keyed to the group
    slug so the admin 'Link existing Group' action can find and activate it.

    Body (all optional — org_name and email are derived from group + user):
        org_description  str  — what the organization does
        knowledge_goal   str  — one thing the team should always be able to find
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        from prospects.models import BusinessProspect

        group = get_object_or_404(Group, slug=slug, is_active=True)
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_admin():
            return Response({"detail": "Owner or admin required."}, status=status.HTTP_403_FORBIDDEN)

        if group.catalyst_enabled:
            return Response(
                {"detail": "Catalyst is already active for this group."},
                status=status.HTTP_409_CONFLICT,
            )

        if BusinessProspect.objects.filter(slug=group.slug).exists():
            return Response(
                {"detail": "A Catalyst request already exists for this group. An administrator will be in touch."},
                status=status.HTTP_409_CONFLICT,
            )

        contact_name = request.user.get_full_name() or request.user.username
        org_description = request.data.get("org_description", "").strip()
        knowledge_goal = request.data.get("knowledge_goal", "").strip()

        BusinessProspect.objects.create(
            name=group.title,
            slug=group.slug,
            primary_contact_email=request.user.email,
            primary_contact_name=contact_name,
            org_description=org_description,
            knowledge_goal=knowledge_goal,
            status="new",
        )

        return Response(
            {"detail": "Request received. A Mixtape administrator will activate Catalyst for your group."},
            status=status.HTTP_201_CREATED,
        )


class GroupCatalystActivateView(generics.GenericAPIView):
    """
    POST /api/groups/<slug>/catalyst/activate

    Self-serve Catalyst provisioning for an existing group.  Idempotent on
    'pending' (returns 202 without re-queuing).  Requires owner or admin role.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        from catalyst.tasks import provision_catalyst_for_group

        group = get_object_or_404(Group, slug=slug, is_active=True)
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_admin():
            return Response({"detail": "Owner or admin required."}, status=status.HTTP_403_FORBIDDEN)

        if group.catalyst_enabled or group.catalyst_status == "ready":
            return Response({"status": "ready"}, status=status.HTTP_409_CONFLICT)

        if group.catalyst_status == "pending":
            return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)

        Group.objects.filter(pk=group.pk).update(catalyst_status="pending")
        provision_catalyst_for_group.delay(group.pk)

        return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)


class GroupCatalystStatusView(generics.GenericAPIView):
    """
    GET /api/groups/<slug>/catalyst/status

    Returns the current Catalyst provisioning state and, when ready,
    the workspace URL for the frontend polling loop.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True)
        membership = GroupService.get_user_membership(group, request.user)
        if not membership or not membership.is_admin():
            return Response({"detail": "Admin or owner required."}, status=status.HTTP_403_FORBIDDEN)

        workspace_url = get_catalyst_workspace_url(group.slug)

        return Response({
            "status": group.catalyst_status,
            "catalyst_enabled": group.catalyst_enabled,
            "workspace_url": workspace_url if group.catalyst_status == "ready" else None,
        })
