# Follows initiatives 0029: ApertureLogEntry is now InitiativeLogEntry (CTO, 2026-11-04).

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0029_rename_aperturelog_initiativelog"),
        ("scrap", "0001_initial"),
    ]

    operations = [
        migrations.RenameField("scrap", "aperture_log_entry", "initiative_log_entry"),
        migrations.AlterField(
            model_name="scrap",
            name="initiative_log_entry",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scraps", to="initiatives.initiativelogentry"),
        ),
    ]
