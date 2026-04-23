"""
Data migration: LinkedOutput → Relationship (initiative domain, outputs-from).

LinkedOutput source side is a concrete FK to Initiative — both the initiative FK
and the polymorphic output GFK are preserved as GFK endpoints in Relationship.

Row count at migration time: 0 (verified on prod 2026-04-22).
Permission policy: superuser-only gate unchanged (REL-8 open question).
"""
from django.db import migrations


def migrate_linked_outputs(apps, schema_editor):
    LinkedOutput = apps.get_model("initiatives", "LinkedOutput")
    Relationship = apps.get_model("relations", "Relationship")
    RelationshipType = apps.get_model("relations", "RelationshipType")
    ContentType = apps.get_model("contenttypes", "ContentType")

    try:
        rel_type = RelationshipType.objects.get(slug="outputs-from")
    except RelationshipType.DoesNotExist:
        return

    initiative_ct = ContentType.objects.get(app_label="initiatives", model="initiative")

    for lo in LinkedOutput.objects.all():
        if lo.output_content_type_id is None or lo.output_object_id is None:
            continue
        Relationship.objects.create(
            source_content_type=initiative_ct,
            source_object_id=lo.initiative_id,
            target_content_type_id=lo.output_content_type_id,
            target_object_id=lo.output_object_id,
            relationship_type=rel_type,
            notes=lo.note,
            status="active",
            lifecycle="authored",
            visibility="public",
            metadata={},
        )


def reverse_migrate(apps, schema_editor):
    Relationship = apps.get_model("relations", "Relationship")
    Relationship.objects.filter(relationship_type__slug="outputs-from").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0010_agent_commands_mobile"),
        ("relations", "0004_alter_relationshipannotation_options_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_linked_outputs, reverse_migrate),
    ]
