# groups/signals.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import pre_delete
from django.dispatch import receiver


@receiver(pre_delete, sender=get_user_model())
def delete_user_group_data(sender, instance, **kwargs):
    """
    Clean up group data tied to a user before they are deleted.

    GroupMembership uses a GenericForeignKey so Django cannot cascade it
    automatically — we handle it here.  GroupInvitation.invited_user is
    SET_NULL, so we delete pending invitations while the FK is still intact.
    """
    from groups.models import GroupInvitation, GroupMembership

    user_ct = ContentType.objects.get_for_model(instance.__class__)

    GroupMembership.objects.filter(
        member_content_type=user_ct,
        member_object_id=instance.id,
    ).delete()

    GroupInvitation.objects.filter(invited_user=instance).delete()
