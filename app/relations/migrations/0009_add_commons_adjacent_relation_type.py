"""
Add commons/adjacent RelationshipType (Shuttle ADR-0058, SH-2).

commons/adjacent: an edge between two things (CommonsItem) or Places,
undirected, recognized by a person as belonging to one adjacency cluster
(ADR-0058 D6). The one-line reason for the edge lives in
Relationship.notes; the owner (a Group, for now) is recorded in
Relationship.metadata by the same convention CM-4 used for Thread
metadata on commons/continues (see relations/service.py
RelationshipService.continue_thread).
"""
from django.db import migrations

NEW_TYPES = [
    {
        "slug": "adjacent",
        "label": "Adjacent to",
        "inverse_label": "Adjacent to",
        "domain": "commons",
        "is_directed": False,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["commons.CommonsItem", "tapestry.Place"],
    },
]


def add_commons_adjacent_type(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in NEW_TYPES:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def remove_commons_adjacent_type(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in NEW_TYPES]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0008_add_commons_relation_types"),
    ]

    operations = [
        migrations.RunPython(add_commons_adjacent_type, remove_commons_adjacent_type),
    ]
