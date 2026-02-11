# groups/models/membership.py
"""
GroupMembership model - links members to groups with roles and decorators.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models

from fundamentals.bases import BaseModel

from .dec_enums import highest_role, is_admin, is_owner, is_steward


User = get_user_model()


class GroupMembership(BaseModel):
    """
    Links members to groups with roles.

    A member can have multiple roles (stored in ArrayField).
    Typical patterns:
    - Basic member: ['member']
    - Admin: ['member', 'admin']
    - Steward: ['member', 'steward']

    Decorators (capabilities) are stored in MembershipHasDecorator.
    """

    group = models.ForeignKey(
        "Group",
        on_delete=models.CASCADE,
        related_name="memberships"
    )

    # Generic relationship to support User or other memberable types
    member_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE
    )
    member_object_id = models.UUIDField()
    member_object = GenericForeignKey("member_content_type", "member_object_id")

    # New: ArrayField for multiple roles
    roles = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
        help_text="List of roles: ['member', 'admin', 'steward', etc.]"
    )

    # Status flags
    is_active = models.BooleanField(default=True, db_index=True)
    is_pending = models.BooleanField(
        default=False,
        help_text="Awaiting acceptance of invitation"
    )
    is_banned = models.BooleanField(
        default=False,
        help_text="Banned from group"
    )
    is_evicted = models.BooleanField(
        default=False,
        help_text="Removed from group"
    )

    # Invitation tracking
    invited_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="group_invitations_sent"
    )

    date_joined = models.DateTimeField(auto_now_add=True)

    # ============================================================================
    # PHASE 1: Permissions System - Decorators and Additional Permissions
    # ============================================================================
    decorators = models.JSONField(
        default=list,
        blank=True,
        help_text="Semantic decorators applied to this membership (e.g., moderator)"
    )
    additional_permissions = models.JSONField(
        default=list,
        blank=True,
        help_text="Direct permission grants for this member (use sparingly)"
    )

    class Meta:
        db_table = "groups_groupmembership"
        unique_together = [
            ("group", "member_content_type", "member_object_id"),
        ]
        indexes = [
            models.Index(fields=["group", "is_active"]),
            models.Index(fields=["member_content_type", "member_object_id"]),
        ]

    def __str__(self):
        role_display = self.highest_role()
        return f"{self.group.title} → {self.member_object} ({role_display})"

    # ===================
    # Role Check Methods
    # ===================

    def has_role(self, role: str) -> bool:
        """Check if this membership has a specific role."""
        return role in self.roles

    def is_owner(self) -> bool:
        """Check if this member is an owner."""
        return is_owner(self.roles)

    def is_admin(self) -> bool:
        """Check if this member is an admin."""
        return is_admin(self.roles)

    def is_steward(self) -> bool:
        """Check if this member is a steward."""
        return is_steward(self.roles)

    def is_member(self) -> bool:
        """Check if this member has basic member role (everyone should)."""
        return "member" in self.roles

    def highest_role(self) -> str:
        """Get the highest role for display purposes."""
        return highest_role(self.roles)

    # ===================
    # Role Management
    # ===================

    def grant_role(self, role: str) -> bool:
        """
        Grant a role to this membership.

        Args:
            role: Role to grant (e.g., 'admin', 'steward')

        Returns:
            True if role was added, False if already had it
        """
        if role not in self.roles:
            self.roles.append(role)
            self.save(update_fields=["roles"])
            return True
        return False

    def revoke_role(self, role: str) -> bool:
        """
        Revoke a role from this membership.

        Args:
            role: Role to revoke

        Returns:
            True if role was removed, False if didn't have it
        """
        if role in self.roles:
            self.roles.remove(role)
            self.save(update_fields=["roles"])
            return True
        return False

    def set_roles(self, roles: list[str]) -> None:
        """
        Set roles, replacing any existing roles.
        Always ensures 'member' is included.

        Args:
            roles: List of role strings
        """
        # Ensure 'member' is always present
        if "member" not in roles:
            roles = ["member"] + roles

        self.roles = roles
        self.save(update_fields=["roles"])

    # ===================
    # Decorator Helpers
    # ===================

    def has_decorator(self, decorator_code: str) -> bool:
        """
        Check if this membership has a specific decorator.

        Args:
            decorator_code: Decorator code (e.g., 'can__ManageEvents')

        Returns:
            True if membership has the active decorator
        """
        return self.decorator_links.filter(
            decorator__code=decorator_code,
            enabled=True
        ).exists()

    def get_decorators(self):
        """
        Get all active decorators for this membership.

        Returns:
            QuerySet of MembershipDecorator objects
        """
        from .decorators import MembershipDecorator

        return MembershipDecorator.objects.filter(
            membership_links__membership=self,
            membership_links__enabled=True
        ).distinct()

    def get_decorator_codes(self) -> list[str]:
        """
        Get list of active decorator codes for this membership.

        Returns:
            List of decorator code strings
        """
        return list(
            self.decorator_links.filter(enabled=True)
            .values_list("decorator__code", flat=True)
        )

    def add_decorator(self, decorator_code: str, assigned_by=None, source="manual", reason=""):
        """
        Add a decorator to this membership.

        Args:
            decorator_code: Code of the decorator to add
            assigned_by: User who assigned the decorator
            source: How it was assigned ('manual', 'profile', 'system')
            reason: Optional reason for assignment

        Returns:
            MembershipHasDecorator instance (created or existing)

        Raises:
            MembershipDecorator.DoesNotExist if decorator code not found
        """
        from .decorators import MembershipDecorator, MembershipHasDecorator

        decorator = MembershipDecorator.objects.get(code=decorator_code)

        link, created = MembershipHasDecorator.objects.get_or_create(
            membership=self,
            decorator=decorator,
            defaults={
                "enabled": True,
                "source": source,
                "assigned_by": assigned_by,
                "reason": reason,
            }
        )

        # If it existed but was disabled, re-enable it
        if not created and not link.enabled:
            link.enabled = True
            link.assigned_by = assigned_by
            link.reason = reason
            link.save(update_fields=["enabled", "assigned_by", "reason", "modified_at"])

        return link

    def remove_decorator(self, decorator_code: str) -> bool:
        """
        Remove a decorator from this membership.

        Args:
            decorator_code: Code of the decorator to remove

        Returns:
            True if decorator was removed, False if didn't have it
        """
        deleted_count = self.decorator_links.filter(
            decorator__code=decorator_code
        ).delete()[0]

        return deleted_count > 0

    def disable_decorator(self, decorator_code: str) -> bool:
        """
        Disable a decorator (keep the record but mark as disabled).

        Args:
            decorator_code: Code of the decorator to disable

        Returns:
            True if decorator was disabled, False if didn't have it
        """
        updated = self.decorator_links.filter(
            decorator__code=decorator_code,
            enabled=True
        ).update(enabled=False, modified_at=models.functions.Now())

        return updated > 0

    # ===================
    # Class Methods for User Group Membership Queries
    # ===================

    @classmethod
    def get_user_memberships(cls, user):
        """
        Get all memberships for a user (active and inactive).

        Args:
            user: User object

        Returns:
            QuerySet of GroupMembership objects
        """
        user_content_type = ContentType.objects.get_for_model(user.__class__)
        return cls.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.id
        )

    @classmethod
    def get_active_user_memberships(cls, user):
        """
        Get active memberships for a user in active groups.

        Args:
            user: User object

        Returns:
            QuerySet of GroupMembership objects
        """
        user_content_type = ContentType.objects.get_for_model(user.__class__)
        return cls.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            is_banned=False,
            is_evicted=False,
            group__is_active=True
        ).select_related("group")

    @classmethod
    def get_user_admin_memberships(cls, user):
        """
        Get groups where user is an admin.

        Args:
            user: User object

        Returns:
            QuerySet of GroupMembership objects where user is admin
        """
        user_content_type = ContentType.objects.get_for_model(user.__class__)
        return cls.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            roles__contains=["admin"],  # PostgreSQL array contains
            group__is_active=True
        ).select_related("group")

    @classmethod
    def get_user_owner_memberships(cls, user):
        """
        Get groups where user is an owner.

        Args:
            user: User object

        Returns:
            QuerySet of GroupMembership objects where user is owner
        """
        user_content_type = ContentType.objects.get_for_model(user.__class__)
        return cls.objects.filter(
            member_content_type=user_content_type,
            member_object_id=user.id,
            is_active=True,
            roles__contains=["owner"],
            group__is_active=True
        ).select_related("group")

    # ===================
    # Validation
    # ===================

    def clean(self):
        """Ensure 'member' role is always present."""
        super().clean()
        if self.roles and "member" not in self.roles:
            self.roles.insert(0, "member")

    def save(self, *args, **kwargs):
        """Ensure 'member' role is always present before saving."""

        # print(f"💾 SAVING MEMBERSHIP: {self.id}")
        # print(f"   Current roles: {self.roles}")
        # print(f"   Stack trace:")
        # traceback.print_stack()

        if self.roles and "member" not in self.roles:
            self.roles.insert(0, "member")
        elif not self.roles:
            print("   ⚠️ ROLES EMPTY! Resetting to ['member']")
            self.roles = ["member"]

        super().save(*args, **kwargs)
