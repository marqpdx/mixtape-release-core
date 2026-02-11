# groups/services/permissions.py
"""
Permission Service for Phase 1: Foundation

Provides simple role-based permission computation.
Will be enhanced in Phase 2 with permission tree and decorators.
"""


from django.contrib.contenttypes.models import ContentType

from groups.models import GroupMembership


# Phase 1: Simple role → permissions mapping (hardcoded)
# Will be replaced by permission tree in Phase 2A
ROLE_PERMISSIONS = {
    "owner": [
        # All admin permissions
        "create_course",
        "edit_course",
        "delete_course",
        "publish_course",
        "manage_courses",
        "manage_members",
        "invite_members",
        "remove_members",
        "assign_roles",
        "edit_group",
        "manage_group_settings",
        "view_content",
        "view_drafts",
        "enroll_in_courses",
        "can_view_project",
        "can_edit_project",
        "can_create_task",
        "can_move_task",
        "can_edit_task",
        "can_archive_task",

        # Owner-only permissions
        "manage_ownership",
        "set_escrow_owner",
        "transfer_ownership",
    ],

    "admin": [
        # Course management
        "create_course",
        "edit_course",
        "delete_course",
        "publish_course",
        "manage_courses",

        # Member management
        "manage_members",
        "invite_members",
        "remove_members",
        "assign_roles",

        # Group management
        "edit_group",
        "manage_group_settings",

        # Content access
        "view_content",
        "view_drafts",

        # Enrollment
        "enroll_in_courses",

        # Projects
        "can_view_project",
        "can_edit_project",
        "can_create_task",
        "can_move_task",
        "can_edit_task",
        "can_archive_task",
    ],

    "steward": [
        # Course management (limited)
        "create_course",
        "edit_course",
        "publish_course",
        "manage_courses",

        # Member management (limited)
        "invite_members",

        # Content access
        "view_content",
        "view_drafts",

        # Enrollment
        "enroll_in_courses",

        # Projects
        "can_view_project",
        "can_edit_project",
        "can_create_task",
        "can_move_task",
        "can_edit_task",
        "can_archive_task",
    ],

    "coordinator": [
        # Course management (create only)
        "create_course",
        "edit_course",

        # Content access
        "view_content",
        "view_drafts",

        # Enrollment
        "enroll_in_courses",

        # Projects
        "can_view_project",
        "can_edit_project",
        "can_create_task",
        "can_move_task",
        "can_edit_task",
    ],

    "member": [
        # Basic content access
        "view_content",

        # Enrollment
        "enroll_in_courses",

        # Projects
        "can_view_project",
        "can_create_task",
        "can_move_task",
        "can_edit_task",
    ],
}


class PermissionService:
    """
    Service for computing and checking user permissions.

    Phase 1: Simple role-based permissions
    Phase 2A: Will add permission tree with inheritance
    Phase 2B: Will add decorator support
    Phase 4: Will add direct permission grants
    """

    @staticmethod
    def compute_user_permissions(user) -> dict:
        """
        Compute all permissions for a user across all their groups.

        Args:
            user: User instance

        Returns:
            Dict with structure:
            {
                'granted': [...],        # All granted permissions (de-duplicated)
                'effective': [...],      # All effective permissions (same as granted in Phase 1)
                'groups': {              # Per-group breakdown
                    'group_slug': {
                        'roles': [...],
                        'permissions': [...]
                    }
                }
            }
        """
        if not user or not user.is_authenticated:
            return {
                "granted": [],
                "effective": [],
                "groups": {}
            }

        # Get all active memberships for this user
        user_ct = ContentType.objects.get_for_model(user)
        memberships = GroupMembership.objects.filter(
            member_content_type=user_ct,
            member_object_id=user.id,
            is_active=True,
            is_pending=False,
            is_banned=False,
            is_evicted=False
        ).select_related("group")

        all_permissions: set[str] = set()
        groups_data: dict[str, dict] = {}

        # Process each membership
        for membership in memberships:
            group_slug = membership.group.slug
            roles = membership.roles or []

            # Collect permissions from all roles
            group_permissions: set[str] = set()
            for role in roles:
                role_perms = ROLE_PERMISSIONS.get(role, [])
                group_permissions.update(role_perms)

            # Store per-group data
            groups_data[group_slug] = {
                "roles": roles,
                "permissions": sorted(list(group_permissions))
            }

            # Add to global set
            all_permissions.update(group_permissions)

        # Convert to sorted lists for consistency
        granted_list = sorted(list(all_permissions))

        return {
            "granted": granted_list,
            "effective": granted_list,  # In Phase 1, granted = effective
            "groups": groups_data
        }

    @staticmethod
    def can_user_perform_action(user, permission: str, group_slug: str = None) -> bool:
        """
        Check if a user has a specific permission.

        Args:
            user: User instance
            permission: Permission string (e.g., 'create_course')
            group_slug: Optional group slug to check permission within specific group

        Returns:
            bool: True if user has the permission
        """
        if not user or not user.is_authenticated:
            return False

        # Superusers always have all permissions
        if user.is_staff or user.is_superuser:
            return True

        permissions_data = PermissionService.compute_user_permissions(user)

        # If checking within a specific group
        if group_slug:
            group_data = permissions_data["groups"].get(group_slug)
            if not group_data:
                return False
            return permission in group_data["permissions"]

        # Check global permissions across all groups
        return permission in permissions_data["effective"]

    @staticmethod
    def get_user_permissions_in_group(user, group_slug: str) -> list[str]:
        """
        Get all permissions a user has within a specific group.

        Args:
            user: User instance
            group_slug: Group slug

        Returns:
            List of permission strings
        """
        if not user or not user.is_authenticated:
            return []

        permissions_data = PermissionService.compute_user_permissions(user)
        group_data = permissions_data["groups"].get(group_slug)

        if not group_data:
            return []

        return group_data["permissions"]

    @staticmethod
    def get_user_roles_in_group(user, group_slug: str) -> list[str]:
        """
        Get all roles a user has within a specific group.

        Args:
            user: User instance
            group_slug: Group slug

        Returns:
            List of role strings
        """
        if not user or not user.is_authenticated:
            return []

        permissions_data = PermissionService.compute_user_permissions(user)
        group_data = permissions_data["groups"].get(group_slug)

        if not group_data:
            return []

        return group_data["roles"]


# Convenience functions for common checks
def can_create_course(user, group_slug: str) -> bool:
    """Check if user can create courses in a group."""
    return PermissionService.can_user_perform_action(user, "create_course", group_slug)


def can_manage_members(user, group_slug: str) -> bool:
    """Check if user can manage members in a group."""
    return PermissionService.can_user_perform_action(user, "manage_members", group_slug)


def can_edit_group(user, group_slug: str) -> bool:
    """Check if user can edit group settings."""
    return PermissionService.can_user_perform_action(user, "edit_group", group_slug)
