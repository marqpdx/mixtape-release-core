"""
Data migration: Filament → Relationship (commons domain).

Filament uses concrete FKs to CommonsItem — both endpoints materialize to the
same ContentType (commons.CommonsItem). Verb strings use underscores; RelationshipType
slugs use hyphens.

Row count at migration time: 0 (verified on prod 2026-04-22).
"""
from django.db import migrations

VERB_SLUG_MAP = {
    "founded_by": "founded-by",
    "located_in": "located-in",
    "collaborates_with": "collaborates-with",
    "teaches_at": "teaches-at",
    "inspired_by": "inspired-by",
    "affiliated_with": "affiliated-with",
    "program_of": "program-of",
}


def migrate_filaments(apps, schema_editor):
    Filament = apps.get_model("commons", "Filament")
    Relationship = apps.get_model("relations", "Relationship")
    RelationshipType = apps.get_model("relations", "RelationshipType")
    ContentType = apps.get_model("contenttypes", "ContentType")
    CommonsItem = apps.get_model("commons", "CommonsItem")

    # ContentType rows are created by Django's post_migrate signal, which has
    # not run yet during a fresh database migration.  Use get_for_model() so a
    # clean test database can create the historical CommonsItem content type
    # before migrating Filament rows into generic Relationships.
    commons_item_ct = ContentType.objects.get_for_model(CommonsItem)
    type_cache = {rt.slug: rt for rt in RelationshipType.objects.filter(domain="commons")}

    for f in Filament.objects.all():
        slug = VERB_SLUG_MAP.get(f.relation_type)
        rel_type = type_cache.get(slug)
        if rel_type is None:
            continue
        Relationship.objects.create(
            source_content_type=commons_item_ct,
            source_object_id=f.source_id,
            target_content_type=commons_item_ct,
            target_object_id=f.target_id,
            relationship_type=rel_type,
            notes=f.note,
            status="active",
            lifecycle="authored",
            visibility="public",
            metadata={},
        )


def reverse_migrate(apps, schema_editor):
    Relationship = apps.get_model("relations", "Relationship")
    Relationship.objects.filter(relationship_type__domain="commons").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("commons", "0001_initial"),
        ("relations", "0004_alter_relationshipannotation_options_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_filaments, reverse_migrate),
    ]
