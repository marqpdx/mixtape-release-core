# projects/permissions.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from rest_framework import permissions

from groups.services.permissions import PermissionService


User = get_user_model()


def _user_is_sponsor(user, sponsor_content_type, sponsor_object_id):
    user_ct = ContentType.objects.get_for_model(User)
    return sponsor_content_type == user_ct and str(sponsor_object_id) == str(user.id)


def _check_group_permission(user, sponsor_object_id, permission):
    from groups.models import Group
    try:
        sponsor = Group.objects.get(id=sponsor_object_id, is_active=True)
    except Group.DoesNotExist:
        raise Http404
    return PermissionService.can_user_perform_action(
        user,
        permission,
        group_slug=sponsor.slug,
    )


def can_user_access_sponsor(user, sponsor_content_type, sponsor_object_id, permission):
    if not user or not user.is_authenticated:
        return False

    if user.is_staff or user.is_superuser:
        return True

    if _user_is_sponsor(user, sponsor_content_type, sponsor_object_id):
        return True

    if sponsor_content_type.model == "group":
        return _check_group_permission(user, sponsor_object_id, permission)

    return False


class ProjectPermissionBase(permissions.BasePermission):
    required_permission = None

    def has_object_permission(self, request, view, obj):
        project = getattr(obj, "project", obj)
        has_access = can_user_access_sponsor(
            request.user,
            project.sponsor_content_type,
            project.sponsor_object_id,
            self.required_permission,
        )
        if not has_access:
            raise Http404
        return True


class CanViewProject(ProjectPermissionBase):
    required_permission = "can_view_project"


class CanEditProject(ProjectPermissionBase):
    required_permission = "can_edit_project"


class CanCreateTask(ProjectPermissionBase):
    required_permission = "can_create_task"


class CanMoveTask(ProjectPermissionBase):
    required_permission = "can_move_task"


class CanEditTask(ProjectPermissionBase):
    required_permission = "can_edit_task"


class CanArchiveTask(ProjectPermissionBase):
    required_permission = "can_archive_task"
