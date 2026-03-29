# accounts/services.py

"""
Helper access service.

A user has helper access if:
  1. They are a superuser, OR
  2. They have the "helper" Role assigned directly (user.roles), OR
  3. They are a member of a Group that is marked is_helper_group=True
"""


def user_has_helper_access(user) -> bool:
    """
    Returns True if the user should have access to Beacon / helper tools.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    # Direct role assignment
    if hasattr(user, "roles") and user.roles.filter(name="helper").exists():
        return True

    # Group-level inheritance
    try:
        from groups.models import Group
        from django.contrib.contenttypes.models import ContentType
        from groups.models import Membership

        group_ct = ContentType.objects.get_for_model(Group)
        helper_group_ids = Group.objects.filter(
            is_helper_group=True
        ).values_list("id", flat=True)

        if not helper_group_ids:
            return False

        return Membership.objects.filter(
            member_content_type=ContentType.objects.get_for_model(user.__class__),
            member_object_id=str(user.id),
            group_id__in=helper_group_ids,
        ).exists()

    except Exception:
        return False
