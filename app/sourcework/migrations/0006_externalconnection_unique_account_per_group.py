from django.db import migrations, models


def dedupe_duplicate_connections(apps, schema_editor):
    """
    Reassign any SourceGrants pointing at a duplicate ExternalConnection to
    the most-recently-connected duplicate, then delete the stale rows. Real
    duplicates were created by re-running Google OAuth for the same account
    before the callback view deduped on (group, provider, provider_account_id).
    """
    ExternalConnection = apps.get_model("sourcework", "ExternalConnection")
    SourceGrant = apps.get_model("sourcework", "SourceGrant")

    duplicate_keys = (
        ExternalConnection.objects.exclude(provider_account_id="")
        .values("group_id", "provider", "provider_account_id")
        .annotate(count=models.Count("id"))
        .filter(count__gt=1)
    )
    for key in duplicate_keys:
        connections = ExternalConnection.objects.filter(
            group_id=key["group_id"],
            provider=key["provider"],
            provider_account_id=key["provider_account_id"],
        ).order_by("-connected_at", "-created_at")
        canonical = connections.first()
        for stale in connections.exclude(pk=canonical.pk):
            SourceGrant.objects.filter(connection=stale).update(connection=canonical)
            stale.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("sourcework", "0005_rename_sourcework_pd_group_kind_state_idx_sourcework__group_i_e70042_idx"),
    ]

    operations = [
        migrations.RunPython(dedupe_duplicate_connections, migrations.RunPython.noop),
    ]
