"""
Data migration: ArtifactRelation → Relationship (editorial domain).

Verb slug mapping (underscore → hyphen):
  in_conversation_with → in-conversation-with
  part_of              → part-of
  All others are identical.

Row count at migration time: 0 (verified on prod 2026-04-22).
dismissed visibility → status=archived per confirmed decision (CTO 2026-04-22).
lifecycle timestamps preserved in metadata.
"""
from django.db import migrations

VERB_SLUG_MAP = {
    "in_conversation_with": "in-conversation-with",
    "part_of": "part-of",
}


def migrate_artifact_relations(apps, schema_editor):
    ArtifactRelation = apps.get_model("atelier", "ArtifactRelation")
    Relationship = apps.get_model("relations", "Relationship")
    RelationshipType = apps.get_model("relations", "RelationshipType")

    type_cache = {rt.slug: rt for rt in RelationshipType.objects.filter(domain="editorial")}

    for ar in ArtifactRelation.objects.select_related(
        "source_content_type", "target_content_type", "created_by", "acknowledged_by"
    ).all():
        slug = VERB_SLUG_MAP.get(ar.verb, ar.verb)
        rel_type = type_cache.get(slug)
        if rel_type is None:
            continue

        status = "archived" if ar.visibility == "dismissed" else "active"

        metadata = {}
        if ar.acknowledged_at:
            metadata["acknowledged_at"] = ar.acknowledged_at.isoformat()
        if ar.acknowledged_by_id:
            metadata["acknowledged_by"] = str(ar.acknowledged_by_id)
        if ar.mutual_at:
            metadata["mutual_at"] = ar.mutual_at.isoformat()

        Relationship.objects.create(
            source_content_type=ar.source_content_type,
            source_object_id=ar.source_object_id,
            target_content_type=ar.target_content_type,
            target_object_id=ar.target_object_id,
            relationship_type=rel_type,
            lifecycle=ar.status,
            visibility="public" if ar.visibility not in ("members", "private") else ar.visibility,
            notes=ar.note,
            metadata=metadata,
            created_by=ar.created_by,
            status=status,
        )


def reverse_migrate(apps, schema_editor):
    Relationship = apps.get_model("relations", "Relationship")
    Relationship.objects.filter(relationship_type__domain="editorial").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0002_seed_relationship_types"),
        ("atelier", "0003_writingmarkeroccurrence"),
    ]

    operations = [
        migrations.RunPython(migrate_artifact_relations, reverse_migrate),
    ]
