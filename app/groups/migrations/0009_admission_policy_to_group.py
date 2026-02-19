# groups/migrations/0009_admission_policy_to_group.py

"""
Move admission_policy from CommunityGroup to base Group model.
Expand choices to 6 levels.
"""

from django.db import migrations, models


def copy_admission_policy_forward(apps, schema_editor):
    """Copy admission_policy values from CommunityGroup to Group."""
    CommunityGroup = apps.get_model("groups", "CommunityGroup")
    for cg in CommunityGroup.objects.select_related("group").all():
        if cg.admission_policy and cg.admission_policy != "open":
            cg.group.admission_policy = cg.admission_policy
            cg.group.save(update_fields=["admission_policy"])


def copy_admission_policy_backward(apps, schema_editor):
    """Copy admission_policy values back from Group to CommunityGroup."""
    CommunityGroup = apps.get_model("groups", "CommunityGroup")
    for cg in CommunityGroup.objects.select_related("group").all():
        if cg.group.admission_policy in ("open", "invite_only", "application"):
            cg.admission_policy = cg.group.admission_policy
            cg.save(update_fields=["admission_policy"])


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0008_ownership_change_request"),
    ]

    operations = [
        # 1. Add admission_policy to Group with default "open"
        migrations.AddField(
            model_name="group",
            name="admission_policy",
            field=models.CharField(
                choices=[
                    ("open", "Open to All"),
                    ("open_parent_members", "Open to Parent Group Members"),
                    ("application", "Application Required"),
                    ("application_parent_members", "Application from Parent Members"),
                    ("invite_only", "Invite Only"),
                    ("closed", "Closed"),
                ],
                default="open",
                help_text="Controls how new members can join this group",
                max_length=30,
            ),
        ),
        # 2. Copy existing CommunityGroup values to Group
        migrations.RunPython(
            copy_admission_policy_forward,
            copy_admission_policy_backward,
        ),
        # 3. Remove admission_policy from CommunityGroup
        migrations.RemoveField(
            model_name="communitygroup",
            name="admission_policy",
        ),
    ]
