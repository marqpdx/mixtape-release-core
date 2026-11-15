"""
Correct the Leaf model label on the commons relationship types.

Migration 0008 seeded `valid_source_types` / `valid_target_types` as
"writing.Leaf", but Leaf lives in the commons app ("commons.Leaf"). The
constraints were never read, so the error was harmless until now: type
constraints are enforced by RelationshipService (ADR-0042 invariant 6), and
enforcing the old label would reject every real Leaf. Data only; no schema
change. Reversible: the reverse restores "writing.Leaf".
"""
from django.db import migrations

OLD = "writing.Leaf"
NEW = "commons.Leaf"
SLUGS = ["context", "continuation", "continues", "origin", "parallel", "presence"]


def _swap(apps, old, new):
    RelationshipType = apps.get_model("relations", "RelationshipType")
    for rel_type in RelationshipType.objects.filter(slug__in=SLUGS):
        changed = False
        for field in ("valid_source_types", "valid_target_types"):
            values = list(getattr(rel_type, field) or [])
            if old in values:
                setattr(rel_type, field, [new if v == old else v for v in values])
                changed = True
        if changed:
            rel_type.save(update_fields=["valid_source_types", "valid_target_types"])


def correct_labels(apps, schema_editor):
    _swap(apps, OLD, NEW)


def restore_labels(apps, schema_editor):
    _swap(apps, NEW, OLD)


class Migration(migrations.Migration):

    dependencies = [
        ("relations", "0009_add_commons_adjacent_relation_type"),
    ]

    operations = [
        migrations.RunPython(correct_labels, restore_labels),
    ]
