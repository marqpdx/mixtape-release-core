from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0001_initial"),
        ("console", "0004_hubcapture_archived_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="hubcapture",
            name="audio_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hub_capture_audio",
                to="files.storedfile",
            ),
        ),
        migrations.AddField(
            model_name="hubcapture",
            name="transcript_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="hubcapture",
            name="status",
            field=models.CharField(
                choices=[
                    ("processing", "Processing"),
                    ("open", "Open"),
                    ("failed", "Failed"),
                    ("resolved", "Resolved"),
                    ("promoted", "Promoted"),
                ],
                default="open",
                max_length=20,
            ),
        ),
    ]
