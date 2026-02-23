from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0009_seed_transcript_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="seed",
            name="transcript_backend",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
