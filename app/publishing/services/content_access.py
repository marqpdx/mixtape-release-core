# publishing/services/content_access.py

"""
Content Access Service

Handles permission checking for ContentPlacement visibility.
Determines if a user can view a placement based on visibility and target permissions.
"""

from typing import Optional
from django.contrib.auth import get_user_model
from django.utils import timezone


def can_view_placement(placement, user: Optional = None) -> bool:
    """
    Check if a user can view a ContentPlacement.

    Permission logic:
    1. visibility='public' → anyone can view
    2. visibility='scheduled' → only if published_at <= now, or user has edit access
    3. visibility='members' → user must be authenticated and member of target
    4. visibility='private' → user must have explicit access (owner or collaborator)

    Args:
        placement: ContentPlacement instance
        user: User instance or None (anonymous)

    Returns:
        bool: True if user can view the placement
    """
    # Public visibility - anyone can view
    if placement.visibility == 'public':
        return True

    # Scheduled visibility - check if published
    if placement.visibility == 'scheduled':
        # Check if content is published yet
        source = placement.source
        if hasattr(source, 'published_at') and source.published_at:
            if source.published_at <= timezone.now():
                return True

        # If not published yet, only editors can view
        if user and user.is_authenticated:
            return _can_edit_source(source, user)
        return False

    # Anonymous users can't view members-only or private content
    if not user or not user.is_authenticated:
        return False

    # Members-only visibility
    if placement.visibility == 'members':
        return _is_member_of_target(placement.target, user)

    # Private visibility
    if placement.visibility == 'private':
        return _has_private_access(placement, user)

    # Unknown visibility - deny by default
    return False


def _can_edit_source(source, user) -> bool:
    """
    Check if user can edit the source content.

    Args:
        source: Source content object
        user: User instance

    Returns:
        bool: True if user can edit
    """
    # Check if source has author
    if hasattr(source, 'author'):
        return source.author == user

    # Check if source has created_by
    if hasattr(source, 'created_by'):
        return source.created_by == user

    return False


def _is_member_of_target(target, user) -> bool:
    """
    Check if user is a member of the target.

    Args:
        target: Target object (Group, User, etc.)
        user: User instance

    Returns:
        bool: True if user is a member
    """
    # If target is a User, check if it's the same user
    User = get_user_model()
    if isinstance(target, User):
        return target == user

    # If target is a Group, check membership
    if hasattr(target, 'members'):
        return target.members.filter(id=user.id).exists()

    # If target has a can_view method, use it
    if hasattr(target, 'can_view'):
        return target.can_view(user)

    return False


def _has_private_access(placement, user) -> bool:
    """
    Check if user has private access to the placement.

    Private access is granted to:
    - Placement creator (placed_by)
    - Source author/creator
    - Collaborators on the source (if applicable)

    Args:
        placement: ContentPlacement instance
        user: User instance

    Returns:
        bool: True if user has private access
    """
    # Check if user placed this content
    if placement.placed_by == user:
        return True

    # Check if user is the source author/creator
    source = placement.source
    if _can_edit_source(source, user):
        return True

    # Check if user is a collaborator (for collaborative content)
    if hasattr(source, 'collaborators'):
        if source.collaborators.filter(id=user.id).exists():
            return True

    return False


def filter_visible_placements(placements, user: Optional = None):
    """
    Filter a queryset of placements to only those visible to the user.

    Args:
        placements: QuerySet or iterable of ContentPlacement instances
        user: User instance or None (anonymous)

    Returns:
        Filtered list of placements
    """
    return [p for p in placements if can_view_placement(p, user)]


def can_place_content(source, target, user) -> bool:
    """
    Check if a user can place content from source to target.

    Args:
        source: Source content object
        target: Target object (Group, User, etc.)
        user: User instance

    Returns:
        bool: True if user can create a placement
    """
    # Must be authenticated
    if not user or not user.is_authenticated:
        return False

    # Must be able to edit the source
    if not _can_edit_source(source, user):
        return False

    # Check if user can post to target
    User = get_user_model()
    if isinstance(target, User):
        # Can only place to own profile
        return target == user

    # Check if target has permission method
    if hasattr(target, 'can_user_post'):
        return target.can_user_post(user)

    return False
