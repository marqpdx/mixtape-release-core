# apps/groups/participant_sources.py
from django.contrib.auth import get_user_model
from livewire.participant_sources import register
from groups.models import Group, GroupMembership  # adjust to your schema

User = get_user_model()

@register(Group)
def group_participants(group: Group):
    member_ids = GroupMembership.objects.filter(
        group=group, is_active=True
    ).values_list("user_id", flat=True)
    return User.objects.filter(id__in=member_ids)
