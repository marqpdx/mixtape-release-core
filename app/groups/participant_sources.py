# apps/groups/participant_sources.py
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from groups.models import Group, GroupMembership  # adjust to your schema
from livewire.participant_sources import register


User = get_user_model()

@register(Group)
def group_participants(group: Group):
    # PHASE 2: Updated to use GenericForeignKey pattern with ContentType
    # Get the ContentType for CustomUser
    user_content_type = ContentType.objects.get_for_model(User)

    # Filter memberships by content type and extract object IDs
    member_ids = GroupMembership.objects.filter(
        group=group,
        is_active=True,
        member_content_type=user_content_type
    ).values_list("member_object_id", flat=True)

    return User.objects.filter(id__in=member_ids)
