"""
Add Sprig-critical and escape-hatch RelationshipTypes.

Resolves RF-4a–4d (Relational Fabric ADR, decisions/relational-fabric/).

RF-4a: supports (editorial) — Sprig→WritingPiece/argument backing.
RF-4b: blocks (initiative, directed) — inverse_label 'Depends on' encodes
       both directions; one type, two labels per ADR open item resolution.
RF-4c: scheduled-for (initiative) — ties content to Almanac dates.
RF-4d: relates-to (editorial) — governed escape hatch for mobile precommit;
       uses_lifecycle=True enables usage logging per Decision 3.
"""
from django.db import migrations

NEW_TYPES = [
    # RF-4a
    {
        "slug": "supports",
        "label": "Supports",
        "inverse_label": "Supported by",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": True,
        "uses_lifecycle": True,
    },
    # RF-4b — one type, two labels; A blocks B means B depends on A
    {
        "slug": "blocks",
        "label": "Blocks",
        "inverse_label": "Depends on",
        "domain": "initiative",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    # RF-4c
    {
        "slug": "scheduled-for",
        "label": "Scheduled for",
        "inverse_label": "Has scheduled item",
        "domain": "initiative",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    # RF-4d — governed escape hatch; uses_lifecycle=True enables usage logging
    {
        "slug": "relates-to",
        "label": "Relates to",
        "inverse_label": "Related to",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
]


def add_sprig_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in NEW_TYPES:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def remove_sprig_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in NEW_TYPES]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0004_alter_relationshipannotation_options_and_more"),
    ]

    operations = [
        migrations.RunPython(add_sprig_types, remove_sprig_types),
    ]
