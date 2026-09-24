from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sourcework", "0012_opportunityapplicationdraft_opportunity_title"),
    ]

    operations = [
        migrations.AlterField(
            model_name="opportunityapplicationdraft",
            name="status",
            field=models.CharField(
                choices=[("draft", "Draft"), ("ready", "Ready"), ("submitted", "Submitted")],
                db_index=True,
                default="draft",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="opportunityapplicationdraft",
            name="submitted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
