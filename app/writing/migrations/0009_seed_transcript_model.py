from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("writing", "0008_seed_transcript_hashes"),
    ]

    operations = [
        migrations.AddField(
            model_name="seed",
            name="transcript_model",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
