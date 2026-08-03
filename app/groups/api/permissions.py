# groups/api/permissions.py
"""
DRF Permission Classes for Phase 1: Foundation

These permission classes integrate with the PermissionService
to provide declarative API endpoint protection.
"""

from rest_framework import permissions

from groups.services.permissions import PermissionService


class HasPermission(permissions.BasePermission):
    """
    Base permission class that checks if user has a specific permission.

    Usage in views:
        permission_classes = [HasPermission]
        required_permission = 'create_course'
        required_group_slug = 'group_slug'  # optional, extracted from kwargs

    Or subclass for specific permissions (see examples below).
    """

    required_permission = None  # Override in subclass
    required_group_slug_param = "slug"  # URL parameter name for group slug

    def has_permission(self, request, view):
        """Check if user has the required permission."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Get permission from view or subclass
        permission = getattr(view, "required_permission", None) or self.required_permission

        if not permission:
            raise ValueError(
                f"{self.__class__.__name__} requires 'required_permission' "
                "to be defined on the view or class"
            )

        # Get group slug from URL kwargs if present
        slug_param = getattr(view, "required_group_slug_param", None) or self.required_group_slug_param
        group_slug = view.kwargs.get(slug_param)

        # Check permission
        return PermissionService.can_user_perform_action(
            request.user,
            permission,
            group_slug=group_slug
        )


class HasAnyPermission(permissions.BasePermission):
    """
    Permission class that checks if user has ANY of the specified permissions.

    Usage in views:
        permission_classes = [HasAnyPermission]
        required_permissions = ['create_course', 'edit_course']
        required_group_slug = 'group_slug'  # optional
    """

    required_permissions = None  # Override in subclass (list)
    required_group_slug_param = "slug"

    def has_permission(self, request, view):
        """Check if user has any of the required permissions."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Get permissions from view or subclass
        permissions_list = getattr(view, "required_permissions", None) or self.required_permissions

        if not permissions_list:
            raise ValueError(
                f"{self.__class__.__name__} requires 'required_permissions' "
                "to be defined on the view or class"
            )

        # Get group slug from URL kwargs if present
        slug_param = getattr(view, "required_group_slug_param", None) or self.required_group_slug_param
        group_slug = view.kwargs.get(slug_param)

        # Check if user has any of the permissions
        for permission in permissions_list:
            if PermissionService.can_user_perform_action(
                request.user,
                permission,
                group_slug=group_slug
            ):
                return True

        return False


class HasAllPermissions(permissions.BasePermission):
    """
    Permission class that checks if user has ALL of the specified permissions.

    Usage in views:
        permission_classes = [HasAllPermissions]
        required_permissions = ['create_course', 'manage_courses']
        required_group_slug = 'group_slug'  # optional
    """

    required_permissions = None  # Override in subclass (list)
    required_group_slug_param = "slug"

    def has_permission(self, request, view):
        """Check if user has all of the required permissions."""
        if not request.user or not request.user.is_authenticated:
            return False

        # Get permissions from view or subclass
        permissions_list = getattr(view, "required_permissions", None) or self.required_permissions

        if not permissions_list:
            raise ValueError(
                f"{self.__class__.__name__} requires 'required_permissions' "
                "to be defined on the view or class"
            )

        # Get group slug from URL kwargs if present
        slug_param = getattr(view, "required_group_slug_param", None) or self.required_group_slug_param
        group_slug = view.kwargs.get(slug_param)

        # Check if user has all of the permissions
        for permission in permissions_list:
            if not PermissionService.can_user_perform_action(
                request.user,
                permission,
                group_slug=group_slug
            ):
                return False

        return True


# ============================================================================
# Specific Permission Classes (Examples)
# ============================================================================

class CanCreateCourseInGroup(HasPermission):
    """Check if user can create courses in the group specified by URL slug."""
    required_permission = "create_course"


class CanManageMembersInGroup(HasPermission):
    """Check if user can manage members in the group specified by URL slug."""
    required_permission = "manage_members"


class CanEditGroup(HasPermission):
    """Check if user can edit group settings."""
    required_permission = "edit_group"


class CanManageCourses(HasPermission):
    """Check if user can manage courses (higher level permission)."""
    required_permission = "manage_courses"


class CanPublishCourse(HasPermission):
    """Check if user can publish courses."""
    required_permission = "publish_course"


class CanDeleteCourse(HasPermission):
    """Check if user can delete courses."""
    required_permission = "delete_course"


class CanViewDrafts(HasPermission):
    """Check if user can view draft content."""
    required_permission = "view_drafts"


class CanInviteMembers(HasPermission):
    """Check if user can invite members to the group."""
    required_permission = "invite_members"


class CanRemoveMembers(HasPermission):
    """Check if user can remove members from the group."""
    required_permission = "remove_members"


class CanAssignRoles(HasPermission):
    """Check if user can assign roles to group members."""
    required_permission = "assign_roles"


# ============================================================================
# Composite Permission Classes (Examples)
# ============================================================================

class CanCreateOrEditCourse(HasAnyPermission):
    """Check if user can create OR edit courses."""
    required_permissions = ["create_course", "edit_course"]


class CanManageGroupAndMembers(HasAllPermissions):
    """Check if user can manage both group settings AND members."""
    required_permissions = ["edit_group", "manage_members"]


class IsGroupStewardOrAbove(HasPermission):
    """Steward, Admin, or Owner of the group in the URL slug. Required for all Crossroads Page management endpoints (DB-0002 Decision 7)."""
    required_permission = "manage_public_page"
