from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sourcework", "0010_opportunity_resume_assets"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunityapplicationdraft",
            name="letter_body_json",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
