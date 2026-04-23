from django.db import migrations


class Migration(migrations.Migration):
    """
    Drop the atelier_artifactrelation table.
    Superseded by relations.Relationship (ADR-0042 REL-6).
    Row count at migration time: 0 (verified on prod 2026-04-22).
    """

    dependencies = [
        ("atelier", "0003_writingmarkeroccurrence"),
        ("relations", "0003_migrate_artifact_relation"),
    ]

    operations = [
        migrations.DeleteModel(name="ArtifactRelation"),
    ]
