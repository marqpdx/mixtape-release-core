"""
Add circle-produces RelationshipType for CR-001 (Circle Decorators & Deliverable Intent).

circle-produces: directed structural relation from a Circle (Group) to its target
artifact (Puddlejump document, Dispatch, or Finding). Created when a Circle with
hasDeliverableIntent links to the artifact it produced or is working toward.
"""
from django.db import migrations

NEW_TYPES = [
    {
        "slug": "circle-produces",
        "label": "Produces",
        "inverse_label": "Produced by",
        "domain": "structural",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["groups.Group"],
    },
]


def add_circle_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in NEW_TYPES:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def remove_circle_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in NEW_TYPES]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0006_add_rf5_relation_types"),
    ]

    operations = [
        migrations.RunPython(add_circle_types, remove_circle_types),
    ]
