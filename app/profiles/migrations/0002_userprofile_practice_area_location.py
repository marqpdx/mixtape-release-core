from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("profiles", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="practice_area",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Primary practice area or discipline (e.g. Product, Engineering, Design).",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="location",
            field=models.CharField(
                blank=True,
                default="",
                help_text="City, region, or remote.",
                max_length=120,
            ),
        ),
    ]
