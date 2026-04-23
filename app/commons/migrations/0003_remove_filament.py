from django.db import migrations


class Migration(migrations.Migration):
    """
    Drop the commons_filament table.
    Superseded by relations.Relationship (ADR-0042 REL-7).
    Row count at migration time: 0 (verified on prod 2026-04-22).
    """

    dependencies = [
        ("commons", "0002_migrate_filament"),
    ]

    operations = [
        migrations.DeleteModel(name="Filament"),
    ]
