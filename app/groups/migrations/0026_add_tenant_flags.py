from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0025_add_public_page"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="crossroads_enabled",
            field=models.BooleanField(
                default=False,
                help_text="This group is active as a Crossroads tenant.",
            ),
        ),
        migrations.AddField(
            model_name="group",
            name="catalyst_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Catalyst features are enabled for this group.",
            ),
        ),
        migrations.AddField(
            model_name="group",
            name="in_crossroads_commons",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "This group has explicitly opted into the Crossroads public directory. "
                    "Must default False — every group is standalone until an admin sets this."
                ),
            ),
        ),
    ]
