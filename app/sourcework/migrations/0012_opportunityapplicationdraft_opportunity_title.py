from django.db import migrations, models


def populate_opportunity_titles(apps, schema_editor):
    draft_model = apps.get_model("sourcework", "OpportunityApplicationDraft")
    for draft in draft_model.objects.select_related("opportunity").iterator():
        title = str((draft.opportunity.normalized_payload or {}).get("title") or "")
        if title:
            draft.opportunity_title = title
            draft.save(update_fields=["opportunity_title"])


class Migration(migrations.Migration):

    dependencies = [
        ("sourcework", "0011_opportunityapplicationdraft_letter_body_json"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunityapplicationdraft",
            name="opportunity_title",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(populate_opportunity_titles, migrations.RunPython.noop),
    ]
