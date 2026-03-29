from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0009_admission_policy_to_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="is_helper_group",
            field=models.BooleanField(
                default=False,
                help_text="Members of this group automatically receive Beacon (helper) access.",
            ),
        ),
    ]
