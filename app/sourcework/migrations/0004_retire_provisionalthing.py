from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("groups", "0001_initial"),
        ("sourcework", "0003_provisionaldata_provisionaldatamembership_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Drop WorkingSetMembership before ProvisionalThing (FK dependency).
        migrations.DeleteModel(
            name="WorkingSetMembership",
        ),
        migrations.DeleteModel(
            name="ProvisionalThing",
        ),
        # Add group FK to ProvisionalData (nullable so existing rows are unaffected).
        migrations.AddField(
            model_name="provisionaldata",
            name="group",
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="provisional_data_records",
                to="groups.group",
            ),
        ),
        migrations.AddIndex(
            model_name="provisionaldata",
            index=models.Index(fields=["group", "kind", "state"], name="sourcework_pd_group_kind_state_idx"),
        ),
        # Rename related_name on source_evidence FK to avoid collision with group FK.
        migrations.AlterField(
            model_name="provisionaldata",
            name="source_evidence",
            field=models.ForeignKey(
                blank=True,
                help_text="SourceEvidence record that grounds this provisional finding.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="grounded_provisional_data",
                to="sourcework.sourceevidence",
            ),
        ),
    ]
