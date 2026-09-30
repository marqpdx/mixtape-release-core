# api/writing/permissions.py
from rest_framework.permissions import BasePermission

from groups.services.permissions import PermissionService
from dispatch.access import can_access_group_dispatch_piece, accessible_dispatch_content


def can_edit_others_group_writing(user, piece):
    if not user or not user.is_authenticated:
        return False
    if not piece.sponsor_content_type or piece.sponsor_content_type.model != "group":
        return False

    from groups.models import Group

    try:
        sponsor = Group.objects.get(id=piece.sponsor_object_id, is_active=True)
    except Group.DoesNotExist:
        return False
    return (
        PermissionService.can_user_perform_action(user, "edit_writing", group_slug=sponsor.slug)
        and PermissionService.can_user_perform_action(
            user, "edit_others_writing", group_slug=sponsor.slug
        )
    )


class IsOwner(BasePermission):
    def has_object_permission(self, request, view, obj):
        # WritingDraft has .author
        return getattr(obj, "author_id", None) == getattr(request.user, "id", None)


class CanEditWritingPiece(BasePermission):
    """
    Author, dispatch collaborator, or a group member with both edit_writing and
    edit_others_writing. Editing another author's piece does not grant deletion.
    Uses PermissionService for consistent permission checking.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if not can_access_group_dispatch_piece(user, obj):
            return False

        # Authorship does not override a read-only Dispatch assignment.
        if obj.author_id == user.id:
            from writing.models import WorkingDocument
            linked = WorkingDocument.objects.filter(piece=obj, dispatch_content__isnull=False)
            if linked.exists():
                return linked.filter(
                    dispatch_content__in=accessible_dispatch_content(user, write=True)
                ).exists()
            return True

        if request.method == "DELETE":
            return False

        # Collaborative dispatch documents are edited through the author's shared
        # working document. Once a user is an assigned collaborator, they should
        # be allowed through this gate even if they are not the piece author.
        from writing.models import WorkingDocument

        if WorkingDocument.objects.filter(
            piece=obj,
            dispatch_content__in=accessible_dispatch_content(user, write=True),
        ).exists():
            return True

        return can_edit_others_group_writing(user, obj)


class CanEditWritingPieceDetails(BasePermission):
    """Detail edits require authorship or group-scoped cross-author authority."""

    def has_object_permission(self, request, view, obj):
        if not can_access_group_dispatch_piece(request.user, obj):
            return False
        if obj.author_id == getattr(request.user, "id", None):
            from writing.models import WorkingDocument
            linked = WorkingDocument.objects.filter(piece=obj, dispatch_content__isnull=False)
            if linked.exists():
                return linked.filter(
                    dispatch_content__in=accessible_dispatch_content(request.user, write=True)
                ).exists()
            return True
        if request.method == "DELETE":
            return False
        return can_edit_others_group_writing(request.user, obj)


class CanPublishWritingPiece(BasePermission):
    """
    Narrower: only certain roles can publish writing.
    Author OR has publish_writing permission in the piece's sponsor group.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if not can_access_group_dispatch_piece(user, obj):
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
                return PermissionService.can_user_perform_action(
                    user,
                    "publish_writing",
                    group_slug=sponsor.slug
                )
            except Group.DoesNotExist:
                return False

        return False
