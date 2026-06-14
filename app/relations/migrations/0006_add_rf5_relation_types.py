"""
Add RF-5 RelationshipTypes for general modeling correctness.

RF-5a: member-of (social) — Person↔Group/Commons-org membership.
       affiliated-with (commons) is org-to-org and not a fit for person membership.
RF-5b: supersedes (structural) — "different thing, one wins"; distinct from
       version-of ("same thing, different state").
"""
from django.db import migrations

NEW_TYPES = [
    # RF-5a
    {
        "slug": "member-of",
        "label": "Member of",
        "inverse_label": "Has member",
        "domain": "social",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    # RF-5b
    {
        "slug": "supersedes",
        "label": "Supersedes",
        "inverse_label": "Superseded by",
        "domain": "structural",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
]


def add_rf5_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in NEW_TYPES:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def remove_rf5_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in NEW_TYPES]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0005_add_sprig_relation_types"),
    ]

    operations = [
        migrations.RunPython(add_rf5_types, remove_rf5_types),
    ]
