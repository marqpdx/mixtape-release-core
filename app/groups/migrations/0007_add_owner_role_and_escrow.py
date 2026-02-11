# Generated manually for Group Ownership Safety Phase A

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def add_owner_role_to_creators(apps, schema_editor):
    """
    For each existing group, find the membership for submitted_by (creator)
    and add 'owner' to their roles if not already present.
    Also set escrow_owner to submitted_by.
    """
    Group = apps.get_model("groups", "Group")
    GroupMembership = apps.get_model("groups", "GroupMembership")
    ContentType = apps.get_model("contenttypes", "ContentType")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    user_ct = ContentType.objects.get_for_model(User)

    for group in Group.objects.select_related("submitted_by").all():
        if not group.submitted_by_id:
            continue

        # Set escrow_owner to creator
        group.escrow_owner_id = group.submitted_by_id
        group.save(update_fields=["escrow_owner_id"])

        # Find creator's membership and add owner role
        membership = GroupMembership.objects.filter(
            group=group,
            member_content_type=user_ct,
            member_object_id=group.submitted_by_id,
            is_active=True,
        ).first()

        if membership and "owner" not in membership.roles:
            membership.roles.append("owner")
            membership.save(update_fields=["roles"])


def remove_owner_role_from_creators(apps, schema_editor):
    """Reverse: remove 'owner' from all memberships and clear escrow_owner."""
    Group = apps.get_model("groups", "Group")
    GroupMembership = apps.get_model("groups", "GroupMembership")

    Group.objects.update(escrow_owner=None)

    for membership in GroupMembership.objects.all():
        if "owner" in membership.roles:
            membership.roles.remove("owner")
            membership.save(update_fields=["roles"])


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0006_groupoverviewlayout_deleted_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="escrow_owner",
            field=models.ForeignKey(
                blank=True,
                help_text="Designated recovery owner for continuity",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="escrow_owned_groups",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="group",
            name="ownership_change_delay_seconds",
            field=models.IntegerField(
                default=86400,
                help_text="Delay in seconds before ownership changes execute (default 24h)",
            ),
        ),
        migrations.RunPython(
            add_owner_role_to_creators,
            remove_owner_role_from_creators,
        ),
    ]
