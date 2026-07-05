from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("media_capture", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mediacapture",
            name="purpose",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
