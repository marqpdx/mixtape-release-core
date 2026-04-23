from django.db import migrations


class Migration(migrations.Migration):
    """
    Drop the initiatives_linkedoutput table.
    Superseded by relations.Relationship (ADR-0042 REL-9).
    Row count at migration time: 0 (verified on prod 2026-04-22).
    """

    dependencies = [
        ("initiatives", "0011_migrate_linked_output"),
    ]

    operations = [
        migrations.DeleteModel(name="LinkedOutput"),
    ]
