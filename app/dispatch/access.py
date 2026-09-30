"""Current-user access to Dispatch content and its linked writing drafts."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef

from dispatch.models import DispatchContent
from groups.models import Group, GroupMembership
from writing.models import WorkingDocument


def active_group_ids(user):
    if not user or not user.is_authenticated:
        return GroupMembership.objects.none().values("group_id")
    return GroupMembership.objects.filter(
        member_content_type=ContentType.objects.get_for_model(user),
        member_object_id=user.pk,
        group__is_active=True,
        is_active=True,
        is_pending=False,
        is_banned=False,
        is_evicted=False,
    ).values("group_id")


def accessible_dispatch_content(user, *, write=False):
    """Require assignment and current membership for every linked group draft."""
    if not user or not user.is_authenticated:
        return DispatchContent.objects.none()

    group_type = ContentType.objects.get_for_model(Group)
    inaccessible_group_draft = WorkingDocument.objects.filter(
        dispatch_content_id=OuterRef("pk"),
        piece__sponsor_content_type=group_type,
    ).exclude(piece__sponsor_object_id__in=active_group_ids(user))

    assignments = {"collaborator_assignments__user": user}
    if write:
        assignments["collaborator_assignments__role"] = "editor"
    return (
        DispatchContent.objects.filter(**assignments)
        .annotate(_inaccessible_group_draft=Exists(inaccessible_group_draft))
        .filter(_inaccessible_group_draft=False)
        .distinct()
    )


def can_access_dispatch_content(user, content, *, write=False):
    return accessible_dispatch_content(user, write=write).filter(pk=content.pk).exists()


def can_access_group_dispatch_piece(user, piece):
    """Revoked group authors cannot use a linked Dispatch draft via piece routes."""
    if not user or not user.is_authenticated:
        return False
    group_type = ContentType.objects.get_for_model(Group)
    if piece.sponsor_content_type_id != group_type.pk:
        return True
    if not WorkingDocument.objects.filter(piece=piece, dispatch_content__isnull=False).exists():
        return True
    return active_group_ids(user).filter(group_id=piece.sponsor_object_id).exists()
