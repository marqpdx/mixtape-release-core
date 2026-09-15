from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0035_group_tagline"),
    ]

    operations = [
        migrations.RenameField(
            model_name="group",
            old_name="in_crossroads_commons",
            new_name="in_crossroads_directory",
        ),
    ]
