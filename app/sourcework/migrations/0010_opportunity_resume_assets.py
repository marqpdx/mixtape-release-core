import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0003_initial"),
        ("sourcework", "0009_opportunityapplicationdraft"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunityprofile",
            name="resume_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="opportunity_profiles",
                to="assets.asset",
            ),
        ),
        migrations.AddField(
            model_name="opportunityapplicationdraft",
            name="resume_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="opportunity_application_drafts",
                to="assets.asset",
            ),
        ),
    ]
