from django.db import migrations, models
import django.db.models.deletion


def backfill_group_permission_profile(apps, schema_editor):
    MembershipHasDecorator = apps.get_model("groups", "MembershipHasDecorator")

    links = MembershipHasDecorator.objects.filter(
        source="profile",
        membership__permission_profile__isnull=False,
    ).select_related("membership__permission_profile")

    for link in links.iterator():
        link.source_group_permission_profile_id = link.membership.permission_profile_id
        link.save(update_fields=["source_group_permission_profile"])


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0012_grouppermissionprofile_and_membership_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="membershiphasdecorator",
            name="source_group_permission_profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="decorator_assignments",
                to="groups.grouppermissionprofile",
            ),
        ),
        migrations.RunPython(
            backfill_group_permission_profile,
            migrations.RunPython.noop,
        ),
    ]
