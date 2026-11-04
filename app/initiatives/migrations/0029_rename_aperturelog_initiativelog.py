# ApertureLog is renamed InitiativeLog (CTO, 2026-11-04; ST-3 Part B).
# Renames only: tables, the entry's foreign key column and index names move; no rows change.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("initiatives", "0028_actionrun_outcome_and_more"),
        # scrap's first migration points at ApertureLogEntry; it must exist before the rename.
        ("scrap", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel("ApertureLog", "InitiativeLog"),
        migrations.RenameModel("ApertureLogEntry", "InitiativeLogEntry"),
        migrations.RenameField("initiativelogentry", "aperture_log", "initiative_log"),
        migrations.RemoveIndex("initiativelogentry", "initiatives_apertur_1981ae_idx"),
        migrations.RemoveIndex("initiativelogentry", "initiatives_apertur_ad2404_idx"),
        migrations.RemoveIndex("initiativelogentry", "initiatives_apertur_fbf1bd_idx"),
        migrations.AddIndex("initiativelogentry", models.Index(fields=["initiative_log", "created_at"], name="initiatives_initiat_80e1bf_idx")),
        migrations.AddIndex("initiativelogentry", models.Index(fields=["initiative_log", "kind"], name="initiatives_initiat_50aeac_idx")),
        migrations.AddIndex("initiativelogentry", models.Index(fields=["initiative_log", "kind", "emph_is_summary_candidate"], name="initiatives_initiat_1adfae_idx")),
        migrations.AlterField(
            model_name="initiativelog",
            name="initiative",
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="initiative_log", to="initiatives.initiative"),
        ),
        migrations.AlterField(
            model_name="initiativelog",
            name="last_handoff_at",
            field=models.DateTimeField(blank=True, help_text="Denormalized — updated on every InitiativeLogEntry with kind='handoff'.", null=True),
        ),
        migrations.AlterField(
            model_name="initiativelogentry",
            name="created_by",
            field=models.ForeignKey(blank=True, help_text="Null for system-generated entries.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="initiative_log_entries", to=settings.AUTH_USER_MODEL),
        ),
    ]
