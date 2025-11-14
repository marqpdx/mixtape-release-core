# groups/utils.py

from django.contrib.contenttypes.models import ContentType
from groups.models import Group
from users.models import CustomUser

def prefetch_members(memberships_qs):
    """
    Prefetches CustomUser and Group objects for a queryset of GroupMemberships.
    Attaches the .member attribute to each membership.
    """

    # Step 1 - Pull ContentTypes
    user_ct = ContentType.objects.get_for_model(CustomUser)
    group_ct = ContentType.objects.get_for_model(Group)

    # Step 2 - Gather IDs by type
    user_ids = memberships_qs.filter(
        member_content_type=user_ct
    ).values_list("member_object_id", flat=True)

    group_ids = memberships_qs.filter(
        member_content_type=group_ct
    ).values_list("member_object_id", flat=True)

    # Step 3 - Fetch objects in bulk
    users = CustomUser.objects.filter(id__in=user_ids).select_related("profile")
    user_map = {u.id: u for u in users}

    groups = Group.objects.filter(id__in=group_ids)
    group_map = {g.id: g for g in groups}

    # Step 4 - Attach .member to each membership
    result = []
    for membership in memberships_qs:
        if membership.member_content_type_id == user_ct.id:
            membership.member = user_map.get(membership.member_object_id)
        elif membership.member_content_type_id == group_ct.id:
            membership.member = group_map.get(membership.member_object_id)
        else:
            membership.member = None

        result.append(membership)

    return result



def get_sorting_params(request, allowed_fields=None):
    allowed_fields = allowed_fields or {"created_at", "title", "group_type"}
    sort_field = request.GET.get("_sort", "created_at")
    sort_order = request.GET.get("_order", "desc")

    # Prevent invalid fields or potential injection
    if sort_field not in allowed_fields:
        sort_field = "created_at"

    if sort_order == "desc":
        return f"-{sort_field}"
    return sort_field
