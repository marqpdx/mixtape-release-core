# groups/permissions/__init__.py

from django.contrib.contenttypes.models import ContentType
from rest_framework import permissions

from groups.models import Group, GroupMembership


class IsGroupAdminOrSteward(permissions.BasePermission):
    def has_permission(self, request, view):
        slug = view.kwargs.get("slug")
        if not slug:
            return False

        try:
            group = Group.objects.get(slug=slug)
        except Group.DoesNotExist:
            return False

        if request.user.is_superuser:
            return True

        # Fix: Use GenericForeignKey pattern with ContentType
        user_ct = ContentType.objects.get_for_model(request.user)
        membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        # Fix: Check roles ArrayField using helper methods
        return membership and (membership.is_admin() or membership.is_steward())


class IsGroupAdmin(permissions.BasePermission):
    """Check if user is an admin of the group"""
    def has_permission(self, request, view):
        slug = view.kwargs.get("slug")
        if not slug:
            return False

        try:
            group = Group.objects.get(slug=slug)
        except Group.DoesNotExist:
            return False

        if request.user.is_superuser:
            return True

        user_ct = ContentType.objects.get_for_model(request.user)
        membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        return membership and membership.is_admin()


class HasGroupDecorator(permissions.BasePermission):
    """
    Check if user has a specific decorator for the group.

    Set `required_decorator` on the view to specify which decorator is needed.
    Example: required_decorator = 'can__ManageWriting'
    """
    def has_permission(self, request, view):
        slug = view.kwargs.get("slug")
        if not slug:
            return False

        try:
            group = Group.objects.get(slug=slug)
        except Group.DoesNotExist:
            return False

        if request.user.is_superuser:
            return True

        user_ct = ContentType.objects.get_for_model(request.user)
        membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            member_object_id=request.user.id,
            is_active=True
        ).first()

        if not membership:
            return False

        # Admins have all permissions
        if membership.is_admin():
            return True

        # Check for required decorator
        required_decorator = getattr(view, 'required_decorator', None)
        if not required_decorator:
            # If no specific decorator required, just check if they're a steward
            return membership.is_steward()

        # Check if user has the required decorator
        return required_decorator in membership.get_decorator_codes()


# ============================================================================
# USER MEMBERSHIP CHECKS
# ============================================================================

def isGroupMember(group):
    """
    Check if the current user is a member of the group.

    Note: This requires a request context. For request-independent checks,
    use isGroupMemberUser(user, group) instead.

    Args:
        group: Group instance

    Returns:
        bool: True if user is a member, False otherwise
    """
    # This function assumes it's called within a request context
    # In views, use: group.user_roles is not None and len(group.user_roles) > 0
    return group.user_roles is not None and len(group.user_roles) > 0


def isGroupMemberUser(user, group):
    """
    Check if a specific user is a member of the group (request-independent).

    Args:
        user: User instance
        group: Group instance

    Returns:
        bool: True if user is a member, False otherwise
    """
    if not user or not user.is_authenticated:
        return False

    from groups.models import GroupMembership
    # Fix: Use GenericForeignKey pattern
    user_ct = ContentType.objects.get_for_model(user)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False
    ).exists()


def canUserModerateGroup(group):
    """
    Check if the current user can moderate the group (admin or steward).

    Note: This requires a request context. For request-independent checks,
    use canUserModerateGroupUser(user, group) instead.

    Args:
        group: Group instance

    Returns:
        bool: True if user is admin or steward, False otherwise
    """
    if not group.user_roles:
        return False
    return "admin" in group.user_roles or "steward" in group.user_roles


def canUserModerateGroupUser(user, group):
    """
    Check if a specific user can moderate the group (request-independent).

    Args:
        user: User instance
        group: Group instance

    Returns:
        bool: True if user is admin or steward, False otherwise
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    from groups.models import GroupMembership
    # Fix: Use GenericForeignKey pattern and roles__overlap for ArrayField
    user_ct = ContentType.objects.get_for_model(user)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        roles__overlap=["admin", "steward"],
        is_active=True,
        is_pending=False
    ).exists()


def hasGroupRole(user, group, role):
    """
    Check if a user has a specific role in the group.

    Args:
        user: User instance
        group: Group instance
        role: Role string ('admin', 'steward', 'member')

    Returns:
        bool: True if user has the role, False otherwise
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    from groups.models import GroupMembership
    # Fix: Use GenericForeignKey pattern and roles__contains for ArrayField
    user_ct = ContentType.objects.get_for_model(user)
    return GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        roles__contains=[role],
        is_active=True,
        is_pending=False
    ).exists()


def getUserGroupRoles(user, group):
    """
    Get all roles a user has in a group.

    Args:
        user: User instance
        group: Group instance

    Returns:
        list: List of role strings, or empty list if not a member
    """
    if not user or not user.is_authenticated:
        return []

    from groups.models import GroupMembership
    # Fix: Use GenericForeignKey pattern
    user_ct = ContentType.objects.get_for_model(user)
    membership = GroupMembership.objects.filter(
        group=group,
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False
    ).first()

    if membership:
        return membership.roles if membership.roles else []

    return []


# ============================================================================
# GROUP QUERY HELPERS
# ============================================================================

def getGroupsForUser(user, include_pending=False):
    """
    Get all groups a user is a member of.

    Args:
        user: User instance
        include_pending: Include pending memberships (default: False)

    Returns:
        QuerySet: Groups the user is a member of
    """
    from groups.models import Group, GroupMembership

    if not user or not user.is_authenticated:
        return Group.objects.none()

    # Fix: Use GenericForeignKey pattern
    user_ct = ContentType.objects.get_for_model(user)
    query = GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True
    )

    if not include_pending:
        query = query.filter(is_pending=False)

    group_ids = query.values_list("group_id", flat=True)
    return Group.objects.filter(id__in=group_ids)


def getGroupsUserCanModerate(user):
    """
    Get all groups a user can moderate (admin or steward).

    Args:
        user: User instance

    Returns:
        QuerySet: Groups the user can moderate
    """
    from groups.models import Group, GroupMembership

    if not user or not user.is_authenticated:
        return Group.objects.none()

    if user.is_staff or user.is_superuser:
        return Group.objects.all()

    # Fix: Use GenericForeignKey pattern and roles__overlap for ArrayField
    user_ct = ContentType.objects.get_for_model(user)
    memberships = GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=user.id,
        is_active=True,
        is_pending=False,
        roles__overlap=["admin", "steward"]
    )

    group_ids = memberships.values_list("group_id", flat=True)
    return Group.objects.filter(id__in=group_ids)


# ============================================================================
# GROUP VISIBILITY CHECKS
# ============================================================================

def canUserAccessGroup(user, group):
    """
    Check if a user can access/view a group based on visibility and membership.

    Args:
        user: User instance (can be None/anonymous)
        group: Group instance

    Returns:
        bool: True if user can access the group
    """
    if group.visibility == "public":
        return True

    if not user or not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    return isGroupMemberUser(user, group)



# ============================================================================
# MODEL PERMISSION CHECKS (for content creation)
# ============================================================================

def check_group_model_permissions(user, group, model_type, action):
    """
    Check if a user has permission to perform an action on a model within a group.

    Used for controlling who can create/edit/delete content (courses, modules, lessons)
    within a group context.

    Args:
        user: User instance
        group: Group instance
        model_type: Model type string ('course', 'module', 'lesson', 'lessonblock', etc.)
        action: Action string ('create', 'update', 'delete', 'publish', 'archive')

    Returns:
        bool: True if user has permission, False otherwise

    Examples:
        check_group_model_permissions(request.user, group, 'course', 'create')
        check_group_model_permissions(request.user, group, 'lesson', 'publish')
    """
    # Unauthenticated users have no permissions
    if not user or not user.is_authenticated:
        return False

    # Superusers and staff always have permission
    if user.is_staff or user.is_superuser:
        return True

    # Check if user is a member of the group
    if not isGroupMemberUser(user, group):
        return False

    # For MVP Phase 1, only admins and stewards can create/edit/delete content
    # Can be expanded in Phase 2 for more granular permissions (e.g., 'author' role)
    if action in ["create", "update", "delete", "publish", "unpublish", "archive"]:
        return canUserModerateGroupUser(user, group)

    # Read-only actions (view, list) are allowed for members
    if action in ["view", "list"]:
        return True

    # Default deny for unknown actions
    return False


# ============================================================================
# DECORATOR EXPORTS
# ============================================================================

# Import and re-export decorator functions
from .decorators import MEMBERSHIP_DECORATORS, get_available_decorators

__all__ = [
    'IsGroupAdminOrSteward',
    'IsGroupAdmin',
    'HasGroupDecorator',
    'isGroupMember',
    'isGroupMemberUser',
    'canUserModerateGroup',
    'canUserModerateGroupUser',
    'hasGroupRole',
    'getUserGroupRoles',
    'getGroupsForUser',
    'getGroupsUserCanModerate',
    'canUserAccessGroup',
    'check_group_model_permissions',
    'MEMBERSHIP_DECORATORS',
    'get_available_decorators',
]
