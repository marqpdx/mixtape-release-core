# groups/services/groups.py
"""
Service layer for Group operations.
Handles all business logic for creating, updating, and managing groups.
"""

from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from groups.models import Group, GroupMembership, CommunityGroup
from groups.models.dec_enums import GroupType


class GroupService:
    """Service for Group-related operations."""

    @staticmethod
    @transaction.atomic
    def create_group(
        title: str,
        group_type: str,
        created_by,
        description: str = "",
        visibility: str = "public",
        profile_image: str = None,
        background_image: str = None,
        profile_code: str = None,
        decorator_codes: list[str] = None
    ):
        """
        Create a new group with the creator as admin.

        Args:
            title: Group title
            group_type: Type of group (persona/circle/community/coalition)
            created_by: User creating the group
            description: Group description
            visibility: Group visibility setting
            profile_image: Optional profile image URL
            background_image: Optional background image URL
            profile_code: Optional decorator profile to apply
            decorator_codes: Optional list of decorator codes to apply

        Returns:
            Group instance
        """
        # Create the group
        group = Group(
            title=title.strip(),
            group_type=group_type,
            description=description,
            visibility=visibility,
            profile_image=profile_image,
            background_image=background_image,
            submitted_by=created_by,
            is_active=True
        )
        group.set_sponsor(created_by)
        group.save()

        # Create type-specific detail record if needed
        GroupService._create_type_detail(group)

        # Add creator as admin member with both member and admin roles
        user_content_type = ContentType.objects.get_for_model(created_by)
        GroupMembership.objects.create(
            group=group,
            member_content_type=user_content_type,
            member_object_id=created_by.id,
            roles=['member', 'admin'],  # New: ArrayField with both roles
            is_active=True,
            is_pending=False
        )

        # TODO Phase 3: Apply decorator profile if provided
        # if profile_code:
        #     DecoratorService.apply_profile(group, profile_code, assigned_by=created_by)

        # TODO Phase 3: Apply custom decorators if provided
        # if decorator_codes:
        #     for code in decorator_codes:
        #         DecoratorService.assign_decorator(group, code, assigned_by=created_by)

        return group

    @staticmethod
    def _create_type_detail(group):
        """Create the type-specific detail record for a group."""
        if group.group_type == GroupType.COMMUNITY:
            CommunityGroup.objects.create(group=group)
        elif group.group_type == GroupType.CIRCLE:
            from groups.models import CircleGroup
            CircleGroup.objects.create(group=group)
        elif group.group_type == GroupType.PERSONA:
            from groups.models import PersonaGroup
            PersonaGroup.objects.create(group=group)
        elif group.group_type == GroupType.COALITION:
            from groups.models import CoalitionGroup
            CoalitionGroup.objects.create(group=group)

    @staticmethod
    @transaction.atomic
    def update_group(group, **fields):
        """
        Update group fields.

        Args:
            group: Group instance to update
            **fields: Fields to update

        Returns:
            Updated Group instance
        """
        allowed_fields = [
            'title', 'description', 'visibility',
            'profile_image', 'background_image'
        ]

        for field, value in fields.items():
            if field in allowed_fields and value is not None:
                setattr(group, field, value)

        group.save()
        return group

    @staticmethod
    def get_user_membership(group, user):
        """
        Get a user's membership in a group.

        Args:
            group: Group instance
            user: User instance

        Returns:
            GroupMembership instance or None
        """
        user_content_type = ContentType.objects.get_for_model(user)
        return GroupMembership.objects.filter(
            group=group,
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            is_banned=False,
            is_evicted=False
        ).first()

    @staticmethod
    def is_user_admin(group, user):
        """
        Check if user is an admin of the group.

        Args:
            group: Group instance
            user: User instance

        Returns:
            bool
        """
        membership = GroupService.get_user_membership(group, user)
        return membership.is_admin() if membership else False

    @staticmethod
    def get_user_role(group, user):
        """
        Get user's role in the group for API responses.
        Maps to frontend expectations: 'admin', 'steward', 'member', or None.

        Args:
            group: Group instance
            user: User instance

        Returns:
            str or None: Role name or None if not a member
        """
        membership = GroupService.get_user_membership(group, user)
        if not membership:
            return None

        # Map backend roles to frontend expectations
        # Backend: ['member', 'admin', 'steward']
        # Frontend: 'admin' | 'moderator' | 'member'

        if membership.is_admin():
            return 'admin'
        elif membership.is_steward():
            return 'moderator'  # Map steward -> moderator for frontend
        else:
            return 'member'

    @staticmethod
    def can_user_view_group(group, user):
        """
        Check if user can view this group.

        Args:
            group: Group instance
            user: User instance (can be AnonymousUser)

        Returns:
            bool
        """
        # Public groups visible to all
        if group.visibility == 'public':
            return True

        # Authenticated users can see if they're members
        if user.is_authenticated:
            return GroupService.get_user_membership(group, user) is not None

        return False