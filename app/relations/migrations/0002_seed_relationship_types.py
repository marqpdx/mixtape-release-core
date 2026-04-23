"""
Seed the RelationshipType registry.

OQ-4 resolution (2026-04-22): in-conversation-with is directed with symmetric display.
One authored record; UI renders both ends. is_directed=True.
"""
from django.db import migrations

SEED = [
    # --- Structural ---
    {
        "slug": "contains",
        "label": "Contains",
        "inverse_label": "Contained by",
        "domain": "structural",
        "is_directed": True,
        "allows_position": True,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "precedes",
        "label": "Precedes",
        "inverse_label": "Follows",
        "domain": "structural",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "branches-from",
        "label": "Branches from",
        "inverse_label": "Has branch",
        "domain": "structural",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "version-of",
        "label": "Version of",
        "inverse_label": "Has version",
        "domain": "structural",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    # --- Editorial ---
    {
        "slug": "mentions",
        "label": "Mentions",
        "inverse_label": "Mentioned by",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    {
        "slug": "suggests",
        "label": "Suggests",
        "inverse_label": "Suggested by",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    {
        "slug": "recommends",
        "label": "Recommends",
        "inverse_label": "Recommended by",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": True,
        "uses_lifecycle": True,
    },
    {
        # Directed with symmetric display (OQ-4). One record, UI shows both ends.
        "slug": "in-conversation-with",
        "label": "In conversation with",
        "inverse_label": "In conversation with",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    {
        "slug": "extends",
        "label": "Extends",
        "inverse_label": "Extended by",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    {
        "slug": "part-of",
        "label": "Part of",
        "inverse_label": "Has part",
        "domain": "editorial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    # --- Social ---
    {
        "slug": "attributes-to",
        "label": "Attributes to",
        "inverse_label": "Attributed by",
        "domain": "social",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    {
        "slug": "responds-to",
        "label": "Responds to",
        "inverse_label": "Has response",
        "domain": "social",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": True,
    },
    # --- Commons (migrated from Filament verb vocabulary) ---
    {
        "slug": "founded-by",
        "label": "Founded by",
        "inverse_label": "Founded",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "located-in",
        "label": "Located in",
        "inverse_label": "Location of",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "collaborates-with",
        "label": "Collaborates with",
        "inverse_label": "Collaborates with",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "teaches-at",
        "label": "Teaches at",
        "inverse_label": "Has instructor",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "inspired-by",
        "label": "Inspired by",
        "inverse_label": "Inspired",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "affiliated-with",
        "label": "Affiliated with",
        "inverse_label": "Affiliated with",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "program-of",
        "label": "Program of",
        "inverse_label": "Has program",
        "domain": "commons",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    # --- Initiative ---
    {
        "slug": "contributes-to",
        "label": "Contributes to",
        "inverse_label": "Has contributor",
        "domain": "initiative",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        # Absorbs LinkedOutput semantics
        "slug": "outputs-from",
        "label": "Outputs from",
        "inverse_label": "Has output",
        "domain": "initiative",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "scopes",
        "label": "Scopes",
        "inverse_label": "Scoped by",
        "domain": "initiative",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    # --- Spatial (Tapestry — not yet active) ---
    {
        "slug": "located-at",
        "label": "Located at",
        "inverse_label": "Location of",
        "domain": "spatial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
    {
        "slug": "documents-place",
        "label": "Documents place",
        "inverse_label": "Documented by",
        "domain": "spatial",
        "is_directed": True,
        "allows_position": False,
        "allows_weight": False,
        "uses_lifecycle": False,
    },
]


def seed_relationship_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for entry in SEED:
        RelationshipType.objects.get_or_create(
            slug=entry["slug"],
            defaults={k: v for k, v in entry.items() if k != "slug"},
        )


def unseed_relationship_types(apps, schema_editor):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    slugs = [e["slug"] for e in SEED]
    RelationshipType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_relationship_types, unseed_relationship_types),
    ]
