import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0002_initial"),
        ("files", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatmessage",
            name="message_type",
            field=models.CharField(
                choices=[("text", "Text"), ("voice", "Voice")],
                default="text",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="audio_file",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="chat_messages",
                to="files.storedfile",
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="audio_duration_seconds",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_text",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("pending", "Pending"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_provider",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_model",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_backend",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="transcript_created_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
