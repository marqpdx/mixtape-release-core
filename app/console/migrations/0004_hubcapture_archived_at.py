from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("console", "0003_hubcapture_visibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="hubcapture",
            name="archived_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
