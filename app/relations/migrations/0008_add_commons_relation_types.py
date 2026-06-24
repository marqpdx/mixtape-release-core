"""
Add commons/* RelationshipTypes for Commons (ADR-0049, CM-3).

Purely additive to the existing `commons` domain — no dependency on
relationality Phase 2 (REL-8/REL-9).

commons/presence: Leaf -> User; who was present. Uses lifecycle
(authored -> acknowledged) per OQ-4 — confirmation is notify-only/cosmetic,
never gates Commons visibility.
commons/continues: Leaf -> Leaf; Thread sequencing, ordered by `position`.
commons/origin, commons/context, commons/continuation: Leaf -> artifact;
unconstrained target type (artifact varies by Bridge).
commons/parallel: Leaf <-> artifact; undirected.
"""
from django.db import migrations

NEW_TYPES = [
    {
        "slug": "presence",
        "label": "Present at",
        "inverse_label": "Was present for",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
        "valid_source_types": ["writing.Leaf"],
        "valid_target_types": ["users.CustomUser"],
    },
    {
        "slug": "continues",
        "label": "Continues",
        "inverse_label": "Continued by",
        "domain": "commons",
        "is_directed": True,
        "allows_position": True,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["writing.Leaf"],
        "valid_target_types": ["writing.Leaf"],
    },
    {
        "slug": "origin",
        "label": "Origin of",
        "inverse_label": "Originated from",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["writing.Leaf"],
    },
    {
        "slug": "context",
        "label": "Context for",
        "inverse_label": "Has context in",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["writing.Leaf"],
    },
    {
        "slug": "continuation",
        "label": "Continuation of",
        "inverse_label": "Continued in",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["writing.Leaf"],
    },
    {
        "slug": "parallel",
        "label": "Parallel to",
        "inverse_label": "Parallel to",
        "domain": "commons",
        "is_directed": False,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
        "valid_source_types": ["writing.Leaf"],
    },
]


def add_commons_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in NEW_TYPES:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def remove_commons_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in NEW_TYPES]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0007_add_circle_relation_types"),
    ]

    operations = [
        migrations.RunPython(add_commons_types, remove_commons_types),
    ]
