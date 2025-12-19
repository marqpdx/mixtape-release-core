# api/writing/permissions.py
from rest_framework.permissions import BasePermission

from groups.services.permissions import PermissionService


class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        # WritingDraft has .author
        return getattr(obj, "author_id", None) == getattr(request.user, "id", None)


class CanEditWritingPiece(BasePermission):
    """
    Author OR has edit_writing permission in the piece's sponsor group.
    Uses PermissionService for consistent permission checking.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Author can always edit their own content
        if obj.author_id == user.id:
            return True

        # Check group permissions if sponsored by a group
        if obj.sponsor_content_type and obj.sponsor_content_type.model == "group":
            # Fetch sponsor object manually since GenericForeignKey isn't auto-fetched
            from groups.models import Group
            try:
                sponsor = Group.objects.get(id=obj.sponsor_object_id, is_active=True)
                # Use PermissionService to check if user can edit writing in this group
                # Phase 1: Using 'edit_course' as proxy until 'edit_writing' is added to ROLE_PERMISSIONS
                # TODO Phase 2: Add 'edit_writing' and 'publish_writing' to groups/services/permissions.py
                return PermissionService.can_user_perform_action(
                    user,
                    "edit_course",  # Temporary: admin/steward can edit
                    group_slug=sponsor.slug
                )
            except Group.DoesNotExist:
                return False

        return False


class CanPublishWritingPiece(BasePermission):
    """
    Narrower: only certain roles can publish writing.
    Author OR has publish_writing permission in the piece's sponsor group.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Author can always publish their own content
        if obj.author_id == user.id:
            return True

        # Check group permissions if sponsored by a group
        if obj.sponsor_content_type and obj.sponsor_content_type.model == "group":
            # Fetch sponsor object manually since GenericForeignKey isn't auto-fetched
            from groups.models import Group
            try:
                sponsor = Group.objects.get(id=obj.sponsor_object_id, is_active=True)
                # Use PermissionService to check if user can publish in this group
                # Phase 1: Using 'publish_course' as proxy until 'publish_writing' is added
                # TODO Phase 2: Add 'publish_writing' to groups/services/permissions.py
                return PermissionService.can_user_perform_action(
                    user,
                    "publish_course",  # Temporary: admin/steward can publish
                    group_slug=sponsor.slug
                )
            except Group.DoesNotExist:
                return False

        return False
