from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("writing", "0032_issue_rename_and_editorial_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="writingpiece",
            name="craft_ignored_dimensions",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
