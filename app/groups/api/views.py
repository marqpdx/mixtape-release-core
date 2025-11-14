# groups/api/views.py - Improved and consolidated

import json
import re
from time import timezone
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.api.serializers import GroupSerializer
from activity.models import Action, ActionOutbox
from activity.tasks import fanout_action_task
from groups.models import AnnouncementDismissal, Group, GroupAnnouncement

from activity.models import ActivityType

# from dispatch.api.serializers import PostSerializer
from dispatch.models import Post
from groups.models import Group, InviteLink
from groups.services.groups import GroupService



from groups.services.invitations import InvitationService





from groups.utils import get_sorting_params
# from identity.models import EmblemAvatar  # PHASE 3: Deferred
from profiles.models import UserProfile
from threadworks.api.views import StandardResultsSetPagination
from users.models import CustomUser
from groups.api.serializers import (
    GroupCreateSerializer,
    GroupDetailSerializer,
    GroupListSerializer,
    GroupInvitationSerializer,
    GroupMembershipSerializer,
)
from groups.models import Group, GroupMembership, GroupInvitation
from groups.permissions import IsGroupAdminOrSteward
# from utils.email.shortcode import generate_shortcode
from utils.email.invitations import generate_username_from_email
from utils.tasks import send_transactional_email_task
from writing.api.serializers import WritingPieceSerializer, WritingPlacementSerializer, WritingWorkingCopySerializer
from writing.models import WritingPiece, WritingPlacement, WritingWorkingCopy


from django.db import transaction
from django.shortcuts import get_object_or_404
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from groups.models import Group, GroupMembership
from .serializers import (
    CreateAnnouncementFromContentSerializer,
    GroupAnnouncementSerializer,
    GroupListSerializer,
    GroupDetailSerializer,
    GroupCreateSerializer,
    GroupMembershipListSerializer,
    GroupMembershipSearchSerializer
)
from ..permissions import IsGroupAdminOrSteward


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
                visibility='public'
            ).order_by('-created_at')

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
            ).values_list('group_id', flat=True)

            queryset = Group.objects.filter(
                is_active=True
            ).filter(
                Q(visibility='public') |
                Q(id__in=member_group_ids)
            ).distinct()

        # Optional filtering
        group_type = self.request.query_params.get('type')
        if group_type:
            queryset = queryset.filter(group_type=group_type)

        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        """Create group using service layer"""
        user = self.request.user

        # Use service layer to create group
        group = GroupService.create_group(
            title=serializer.validated_data['title'],
            group_type=serializer.validated_data['group_type'],
            created_by=user,
            description=serializer.validated_data.get('description', ''),
            visibility=serializer.validated_data.get('visibility', 'public'),
            profile_image=serializer.validated_data.get('profile_image'),
            background_image=serializer.validated_data.get('background_image'),
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
        if self.request.method == 'GET':
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
        ).select_related('group').prefetch_related('member_object')

        # Optional filtering
        role = self.request.query_params.get("role")
        if role:
            # Map frontend role to backend role
            backend_role = self._map_frontend_role_to_backend(role)
            # Filter by roles array containing the backend role
            queryset = queryset.filter(roles__contains=[backend_role])

        pending = self.request.query_params.get("pending")
        if pending and pending.lower() == 'true':
            queryset = queryset.filter(is_pending=True)
        else:
            queryset = queryset.filter(is_pending=False)

        return queryset.order_by('date_joined')

    def _map_frontend_role_to_backend(self, frontend_role):
        """Map frontend role names to backend role names"""
        mapping = {
            'admin': 'admin',
            'moderator': 'steward',
            'member': 'member',
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

        search_term = self.request.query_params.get('q', '').strip()
        if not search_term:
            return GroupMembership.objects.none()

        # Search within group members only
        queryset = GroupMembership.objects.filter(
            group=group,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            is_pending=False
        ).select_related('group').prefetch_related('member_object')

        # Filter by search term - this will need customization based on your member types
        # For now, assuming User members with standard fields
        if search_term.startswith('@'):
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
        ).values_list('group_id', flat=True)

        return Group.objects.filter(
            id__in=member_group_ids,
            is_active=True
        ).order_by('title')


class GroupMembersListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated, IsGroupAdminOrSteward]
    serializer_class = GroupMembershipSerializer
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs["slug"]
        group = get_object_or_404(Group, slug=group_slug)

        qs = GroupMembership.objects.filter(group=group)

        role = self.request.query_params.get("role")
        status = self.request.query_params.get("status")

        if role:
            qs = qs.filter(role=role)
        if status:
            qs = qs.filter(status=status)

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


class GroupInvitationDetailView(generics.RetrieveAPIView):
    serializer_class = GroupInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "pk"

    def get_queryset(self):
        group_slug = self.kwargs["group_slug"]
        return GroupInvitation.objects.filter(group__slug=group_slug)


class GroupWritingListCreateView(generics.ListCreateAPIView):
    serializer_class = WritingPlacementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        group = get_object_or_404(Group, slug=self.kwargs["slug"])

        placements = WritingPlacement.objects.filter(
            target_content_type=ContentType.objects.get_for_model(Group),
            target_object_id=group.id,
            channel="feed"
        ).select_related('piece')

        return placements


    def perform_create(self, serializer):
        group = get_object_or_404(Group, slug=self.kwargs["slug"])
        serializer.save(
            sponsor=group,
            submitted_by=self.request.user
        )


class GroupWritingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = WritingPieceSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "slug"

    def get_queryset(self):
        group = get_object_or_404(Group, slug=self.kwargs["slug"])
        return WritingPiece.objects.filter(
            sponsor_content_type=ContentType.objects.get_for_model(Group),
            sponsor_object_id=group.id
        )

    def get_object(self):
        queryset = self.get_queryset()
        piece_slug = self.kwargs["piece_slug"]
        piece = get_object_or_404(queryset, slug=piece_slug)

        # Check if we should show working copy (edit mode) or published version
        show_working_copy = self._should_show_working_copy(piece)

        if show_working_copy:
            try:
                working_copy = WritingWorkingCopy.objects.get(
                    piece=piece,
                    user=self.request.user
                )
                # Apply working copy data if it exists and has content
                if working_copy.body_json and working_copy.body_json.get('content'):
                    piece.title = working_copy.title or piece.title
                    piece.body_json = working_copy.body_json
                    piece.excerpt = working_copy.excerpt or piece.excerpt
            except WritingWorkingCopy.DoesNotExist:
                pass  # Use canonical piece data

        return piece

    def _should_show_working_copy(self, piece):
        """
        Determine whether to show working copy or published version.
        """
        # Always show working copy for PUT/PATCH (editing)
        if self.request.method in ['PUT', 'PATCH']:
            return True

        # Show working copy if explicitly requested via query param
        if self.request.GET.get('edit', '').lower() in ['true', '1']:
            return True

        # Show working copy if user is the author and piece is still draft
        if (piece.author == self.request.user and
            piece.status in ['draft', 'review']):
            return True

        # Otherwise show published version
        return False


class GroupWritingDraftsListView(generics.ListAPIView):
    """
    List all writing drafts (working copies) for a specific group.
    Returns WritingWorkingCopy instances where the associated WritingPiece
    is sponsored by the specified group.
    """
    serializer_class = WritingWorkingCopySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        group_slug = self.kwargs['slug']
        group = get_object_or_404(Group, slug=group_slug)

        # Get working copies for pieces sponsored by this group
        queryset = WritingWorkingCopy.objects.filter(
            piece__sponsor_content_type__model='group',
            piece__sponsor_object_id=group.id,
            piece__status='draft'  # Only include drafts
        ).exclude(
            piece__is_empty=True  # Filter out empty pieces
        ).select_related(
            'piece',
            'user',
            'piece__sponsor_content_type'
        ).prefetch_related(
            'piece__versions'
        ).order_by('-last_saved_at')

        return queryset

    def get_permissions(self):
        """
        Check that user has access to view drafts in this group.
        """
        permissions = super().get_permissions()
        return permissions

    def list(self, request, *args, **kwargs):
        """
        Override to add group context and permission checking.
        """
        group_slug = self.kwargs['slug']
        group = get_object_or_404(Group, slug=group_slug)

        # Check if user has permission to view drafts in this group
        # You can implement your group permission logic here
        # For example:
        if not group.can_user_view_drafts(request.user):
            return Response(
                {"detail": "You don't have permission to view drafts in this group."},
                status=403
            )

        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'drafts': serializer.data,
            'group': {
                'id': group.id,
                'title': group.title,
                'slug': group.slug,
            }
        })



class GroupNoticeBoardView(generics.ListAPIView):
    serializer_class = WritingPlacementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        group_slug = self.kwargs['slug']
        group = get_object_or_404(Group, slug=group_slug)

        # Permission check (assuming this method exists)
        if not group.can_user_view_content(self.request.user):
            return WritingPlacement.objects.none()

        group_ct = ContentType.objects.get_for_model(Group)

        # Return the queryset
        return WritingPlacement.objects.filter(
            target_content_type=group_ct,
            target_object_id=group.id,
            channel='feed',
            visibility__in=self._get_allowed_visibility_levels()
        ).select_related(
            'piece',
            'piece__author',
            'piece__author__profile'  # For avatar
        ).order_by('-placed_at')  # ← Use placed_at, not created_at

    def _get_allowed_visibility_levels(self):
        user = self.request.user
        group_slug = self.kwargs['slug']
        group = Group.objects.get(slug=group_slug)

        allowed = ['public']

        if user.is_authenticated:
            if group.is_member(user):
                allowed.append('members')
            # if group.is_user_admin(user):
            #     allowed.append('private')

        return allowed


class GroupEmblemAttachView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, group_slug):
        group = get_object_or_404(Group, slug=group_slug)

        # Check permissions (user must be admin of group)
        if not request.user.is_superuser:
            if not hasattr(request.user, 'is_admin_of') or not request.user.is_admin_of(group):
                return Response(status=status.HTTP_403_FORBIDDEN)

        emblem_id = request.data.get('emblem_avatar_id')
        if not emblem_id:
            return Response(
                {"error": "emblem_avatar_id required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        emblem = get_object_or_404(EmblemAvatar, id=emblem_id)

        # Check if user can attach this emblem
        if not emblem.can_be_attached_by(request.user):
            return Response(
                {"error": "You don't have permission to use this emblem"},
                status=status.HTTP_403_FORBIDDEN
            )

        group.emblem = emblem
        group.save()

        return Response({"success": True})


class GroupEmblemResetView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, group_slug):
        group = get_object_or_404(Group, slug=group_slug)

        # Check permissions
        if not request.user.is_superuser:
            if not hasattr(request.user, 'is_admin_of') or not request.user.is_admin_of(group):
                return Response(status=status.HTTP_403_FORBIDDEN)

        group.emblem = None
        group.save()

        return Response({"success": True})




# NOTICEBOARD views



class GroupAnnouncementListCreateView(generics.ListCreateAPIView):
    """
    List all announcements for a group or create a new one.
    Only admins/stewards can create.
    """
    serializer_class = GroupAnnouncementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_slug = self.kwargs.get('group_slug')
        group = get_object_or_404(Group, slug=group_slug)

        queryset = GroupAnnouncement.objects.filter(group=group)

        # Non-admins only see active announcements
        user = self.request.user
        if not group.is_admin(user):
            queryset = queryset.filter(is_active=True)

        return queryset.select_related('author', 'source_content_type')

    def perform_create(self, serializer):
        group_slug = self.kwargs.get('group_slug')
        group = get_object_or_404(Group, slug=group_slug)

        if not group.is_admin(self.request.user):
            raise PermissionError("Only admins and stewards can create announcements")

        announcement = serializer.save(
            group=group,
            author=self.request.user
        )

        # If also_send_notification is True, create notifications
        if announcement.also_send_notification and not announcement.notification_sent_at:
            self._send_notifications_to_members(announcement)

    def _send_notifications_to_members(self, announcement):
        """
        Create Notification records for all group members.
        This bridges to the Activity system for critical announcements.
        """
        from activity.models import Action, Notification

        # Create an Action for this announcement
        action = Action.objects.create(
            actor_content_type=ContentType.objects.get_for_model(announcement.author),
            actor_object_id=announcement.author.id,
            verb='announced',
            target_content_type=ContentType.objects.get_for_model(announcement),
            target_object_id=announcement.id,
            bucket='system',
            priority=announcement.priority if announcement.priority == 'critical' else 'normal'
        )

        # Fan-out to all group members
        members = announcement.group.members.all()
        notifications = []

        for member in members:
            if member != announcement.author:  # Don't notify the author
                notifications.append(
                    Notification(
                        action=action,
                        recipient=member,
                        bucket='system',
                        priority=action.priority,
                        dedupe_key=f"announcement:{announcement.id}:user:{member.id}",
                        aggregate_key=f"announcements:group:{announcement.group.id}",
                        last_occurred_at=timezone.now()
                    )
                )

        Notification.objects.bulk_create(notifications)

        # Mark as sent
        announcement.notification_sent_at = timezone.now()
        announcement.save(update_fields=['notification_sent_at'])


class GroupAnnouncementDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete a specific announcement.
    Only admins/stewards can update/delete.
    """
    serializer_class = GroupAnnouncementSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'

    def get_queryset(self):
        group_slug = self.kwargs.get('group_slug')
        group = get_object_or_404(Group, slug=group_slug)
        return GroupAnnouncement.objects.filter(group=group)

    def perform_update(self, serializer):
        group_slug = self.kwargs.get('group_slug')
        group = get_object_or_404(Group, slug=group_slug)

        if not group.is_admin(self.request.user):
            raise PermissionError("Only admins and stewards can update announcements")

        serializer.save()

    def perform_destroy(self, instance):
        group_slug = self.kwargs.get('group_slug')
        group = get_object_or_404(Group, slug=group_slug)

        if not group.is_admin(self.request.user):
            raise PermissionError("Only admins and stewards can delete announcements")

        # Soft delete
        instance.is_active = False
        instance.save(update_fields=['is_active'])


class GroupAnnouncementVisibleQueueView(APIView):
    """
    Get the visible announcement queue for the current user.
    Filters by dismissals and returns in priority order.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, group_slug):
        group = get_object_or_404(Group, slug=group_slug)

        visible = GroupAnnouncement.get_visible_queue_for_user(
            group=group,
            user=request.user
        )

        serializer = GroupAnnouncementSerializer(visible, many=True)
        return Response({
            'count': len(visible),
            'announcements': serializer.data
        })


class GroupAnnouncementDismissView(APIView):
    """
    Dismiss an announcement.
    First dismiss = 48hr snooze
    Second dismiss = permanent
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, group_slug, pk):
        group = get_object_or_404(Group, slug=group_slug)
        announcement = get_object_or_404(GroupAnnouncement, pk=pk, group=group)

        dismissal_type, snooze_until = AnnouncementDismissal.dismiss_announcement(
            announcement=announcement,
            user=request.user
        )

        if dismissal_type == 'snooze':
            message = f"Hidden for 48 hours. Will reappear on {snooze_until.strftime('%b %d at %I:%M %p')}"
        else:
            message = "Dismissed permanently"

        return Response({
            'status': 'dismissed',
            'dismissal_type': dismissal_type,
            'message': message,
            'snoozed_until': snooze_until
        })


class GroupAnnouncementCreateFromContentView(APIView):
    """
    Create an announcement from existing content (course, event, post, etc.)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, group_slug):
        group = get_object_or_404(Group, slug=group_slug)

        if not group.is_admin(request.user):
            return Response(
                {"error": "Only admins and stewards can create announcements"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = CreateAnnouncementFromContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get the content type and object
        content_type = ContentType.objects.get(model=serializer.validated_data['content_type'])

        # Create the announcement
        announcement = GroupAnnouncement.objects.create(
            group=group,
            author=request.user,
            title=serializer.validated_data['title'],
            content=serializer.validated_data['content'],
            priority=serializer.validated_data.get('priority', 'normal'),
            cta_text=serializer.validated_data.get('cta_text', ''),
            cta_url=serializer.validated_data.get('cta_url', ''),
            expires_at=serializer.validated_data.get('expires_at'),
            also_send_notification=serializer.validated_data.get('also_send_notification', False),
            source_content_type=content_type,
            source_object_id=serializer.validated_data['content_id']
        )

        # Send notifications if requested
        if announcement.also_send_notification:
            view = GroupAnnouncementListCreateView()
            view._send_notifications_to_members(announcement)

        response_serializer = GroupAnnouncementSerializer(announcement)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)







@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def invite_to_group(request, slug):
    import traceback

    group = get_object_or_404(Group, slug=slug)

    if group.submitted_by != request.user and not request.user.is_staff:
        return Response({"detail": "Not authorized to invite members."}, status=status.HTTP_403_FORBIDDEN)

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
            print(f"[ERROR] create_invitation failed for username {username}: {e}")
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
            print(f"[DEBUG] About to call create_invitation for {email}")
            invitation, is_existing_user = InvitationService.create_invitation(group, user, email, request.user, message)
            print(f"[DEBUG] create_invitation succeeded for {email}")

            invitations_created.append((invitation, is_existing_user))
        except Exception as e:
            print(f"[ERROR] create_invitation failed for email {email}: {type(e).__name__}: {e}")
            traceback.print_exc()
            errors.append({"email": email, "error": str(e)})

    print(f"[DEBUG] Invitations created: {len(invitations_created)}, Errors: {len(errors)}")
    print(f"[DEBUG] About to call send_batch_invitations")

    # Batch send emails via Celery
    if invitations_created:
        try:
            print(f"[DEBUG] Calling InvitationService.send_batch_invitations with {len(invitations_created)} invitations")
            InvitationService.send_batch_invitations(invitations_created, group, request.user, message)
            print(f"[DEBUG] send_batch_invitations completed successfully")
        except Exception as e:
            print(f"[ERROR] send_batch_invitations failed: {type(e).__name__}: {e}")
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
            "user_was_new": result['user_was_new'],
            "group": {
                "id": str(result['group'].id),
                "title": result['group'].title,
                "slug": result['group'].slug,
            }
        }, status=200)

    except ValidationError as e:
        # Service layer raises ValidationError with specific messages
        return JsonResponse({"error": str(e)}, status=400)

    except Exception as e:
        # Catch any unexpected errors
        return JsonResponse(
            {"error": "An unexpected error occurred."},
            status=500
        )

