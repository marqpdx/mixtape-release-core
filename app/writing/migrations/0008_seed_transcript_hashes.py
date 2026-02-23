from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0007_add_import_receipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="seed",
            name="transcript_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="seed",
            name="body_hash",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="seed",
            name="edited_after_transcription",
            field=models.BooleanField(default=False),
        ),
    ]
