from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0013_agent_transcription_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="aperturelogentry",
            name="archived_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
