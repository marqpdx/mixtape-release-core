# threadworks/permissions.py

from rest_framework import permissions
from django.shortcuts import get_object_or_404


from .models import Forum, Discussion, ForumMembership

class ForumPermissions(permissions.BasePermission):
    """
    Custom permission class for Threadworks forum access
    """

    def has_permission(self, request, view):
        """Check if user has permission to access the forum/discussion"""
        if not request.user.is_authenticated:
            return False

        # Get forum from URL kwargs
        forum_slug = view.kwargs.get('forum_slug')
        if not forum_slug:
            return True  # No forum context, allow other permissions to handle

        try:
            forum = Forum.objects.get(slug=forum_slug, is_archived=False)
        except Forum.DoesNotExist:
            return False

        return self.can_access_forum(request.user, forum)

    def has_object_permission(self, request, view, obj):
        """Check permissions on specific forum/discussion/post objects"""
        if not request.user.is_authenticated:
            return False

        # Handle different object types
        if isinstance(obj, Forum):
            forum = obj
        elif isinstance(obj, Discussion):
            forum = obj.forum
        elif hasattr(obj, 'discussion'):  # Post object
            forum = obj.discussion.forum
        else:
            return False

        # Check basic forum access
        if not self.can_access_forum(request.user, forum):
            return False

        # Additional permissions based on HTTP method
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions
        if request.method in ['POST', 'PUT', 'PATCH']:
            return self.can_post_in_forum(request.user, forum)

        if request.method == 'DELETE':
            return self.can_moderate_forum(request.user, forum) or self.is_owner(request.user, obj)

        return False



    def can_access_forum(self, user, forum):
        """Check if user can view the forum"""
        if forum.visibility == 'public':
            return True
        elif forum.visibility == 'members':
            return user.is_authenticated
        elif forum.visibility == 'group':
            # Check if the sponsor is a Group and user is a member
            if forum.sponsor:
                # Import your Group model at the top of the file
                from groups.models import Group

                # Check if sponsor is a Group
                if isinstance(forum.sponsor, Group):
                    # Check if user is a member of the sponsor group
                    return forum.sponsor.members.filter(id=user.id).exists()
            return False
        return False


    def can_post_in_forum(self, user, forum):
        """Check if user can create posts/discussions in the forum"""
        if not self.can_access_forum(user, forum):
            return False

        # Check if user is banned or has specific posting restrictions
        membership = ForumMembership.objects.filter(forum=forum, user=user).first()
        if membership and not membership.is_active:
            return False

        # For group-only forums, user must be in the sponsor group
        if forum.visibility == 'group':
            from groups.models import Group
            if forum.sponsor and isinstance(forum.sponsor, Group):
                return forum.sponsor.members.filter(id=user.id).exists()
            return False

        return True

    def can_moderate_forum(self, user, forum):
        """Check if user can moderate the forum (edit/delete others' content)"""
        if user.is_superuser or user.is_staff:
            return True

        # Check forum-specific moderator role
        membership = ForumMembership.objects.filter(
            forum=forum,
            user=user,
            role__in=['moderator', 'admin'],
            is_active=True
        ).exists()

        return membership

    def is_owner(self, user, obj):
        """Check if user owns the object (for editing/deleting own content)"""
        if hasattr(obj, 'author'):
            return obj.author == user
        return False

class DiscussionPermissions(permissions.BasePermission):
    """
    Specific permissions for discussion operations
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Read permissions
        if request.method in permissions.SAFE_METHODS:
            return ForumPermissions().can_access_forum(request.user, obj.forum)

        # Check if discussion is locked
        if obj.is_locked and request.method in ['POST', 'PUT', 'PATCH']:
            return ForumPermissions().can_moderate_forum(request.user, obj.forum)

        # Write permissions
        if request.method in ['PUT', 'PATCH']:
            # Can edit own discussions or if moderator
            return (obj.created_by == request.user or
                   ForumPermissions().can_moderate_forum(request.user, obj.forum))

        if request.method == 'DELETE':
            return (obj.created_by == request.user or
                   ForumPermissions().can_moderate_forum(request.user, obj.forum))

        return ForumPermissions().can_post_in_forum(request.user, obj.forum)

class PostPermissions(permissions.BasePermission):
    """
    Specific permissions for post operations
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Read permissions
        if request.method in permissions.SAFE_METHODS:
            return ForumPermissions().can_access_forum(request.user, obj.discussion.forum)

        # Check if discussion is locked
        if obj.discussion.is_locked and request.method in ['POST', 'PUT', 'PATCH']:
            return ForumPermissions().can_moderate_forum(request.user, obj.discussion.forum)

        # Write permissions
        if request.method in ['PUT', 'PATCH']:
            # Can edit own posts or if moderator
            return (obj.author == request.user or
                   ForumPermissions().can_moderate_forum(request.user, obj.discussion.forum))

        if request.method == 'DELETE':
            return (obj.author == request.user or
                   ForumPermissions().can_moderate_forum(request.user, obj.discussion.forum))

        return ForumPermissions().can_post_in_forum(request.user, obj.discussion.forum)

class IsModeratorOrOwner(permissions.BasePermission):
    """
    Permission for actions that require ownership or moderator status
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Get the forum context
        if hasattr(obj, 'forum'):
            forum = obj.forum
        elif hasattr(obj, 'discussion'):
            forum = obj.discussion.forum
        else:
            return False

        # Check if user is owner or moderator
        is_owner = getattr(obj, 'author', None) == request.user
        is_moderator = ForumPermissions().can_moderate_forum(request.user, forum)

        return is_owner or is_moderator