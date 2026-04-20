from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("initiatives", "0007_actionrun"),
    ]

    operations = [
        migrations.AlterField(
            model_name="actionrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
