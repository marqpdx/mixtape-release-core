# groups/signals.py

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver


def _seed_welcome_forum(group):
    """Create Welcome Forum + Tell About Yourself pinned discussion for a group."""
    from threadworks.models import Forum, Discussion

    group_ct = ContentType.objects.get_for_model(group.__class__)

    # Idempotent: skip if Welcome forum already exists for this group
    if Forum.objects.filter(
        sponsor_content_type=group_ct,
        sponsor_object_id=group.id,
        title="Welcome",
    ).exists():
        return

    forum = Forum.objects.create(
        title="Welcome",
        slug="welcome",
        sponsor_content_type=group_ct,
        sponsor_object_id=group.id,
        description="A space for introductions and community agreements.",
        visibility="group",
        audience_type="all_members",
        auto_add_new_members=True,
    )

    Discussion.objects.create(
        forum=forum,
        title="Who We Are",
        slug="who-we-are",
        description=(
            "Share a bit about who you are. "
            "Updating your quick intro on your profile will post here automatically."
        ),
        status="pinned",
        pinned_nav_name="",
        created_by=group.escrow_owner,
    )


@receiver(post_save, sender='groups.Group')
def seed_welcome_forum_on_create(sender, instance, created, **kwargs):
    if created and instance.group_type == "community":
        _seed_welcome_forum(instance)


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
