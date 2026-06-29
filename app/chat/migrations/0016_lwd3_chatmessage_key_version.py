from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0015_lwd2_next_rotation_due_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="message_key_version",
            field=models.PositiveSmallIntegerField(null=True, blank=True),
        ),
    ]
