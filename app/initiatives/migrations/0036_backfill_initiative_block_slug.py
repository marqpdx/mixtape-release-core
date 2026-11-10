# initiatives/migrations/0036_backfill_initiative_block_slug.py
#
# ADR-0064 D3, amended 2026-11-09: any Argus Initiative created under the
# earlier title convention ("Argus: {block_slug}") before this field existed
# gets its block_slug derived from that title, so ensure_block_initiative's
# new block_slug lookup finds it instead of creating a duplicate.

from django.db import migrations

TITLE_PREFIX = "Argus: "


def backfill_block_slug(apps, schema_editor):
    Initiative = apps.get_model("initiatives", "Initiative")
    SurfaceProfile = apps.get_model("surfaces", "SurfaceProfile")
    try:
        argus = SurfaceProfile.objects.get(slug="argus")
    except SurfaceProfile.DoesNotExist:
        return
    for initiative in Initiative.objects.filter(surface=argus, block_slug__isnull=True):
        if initiative.title.startswith(TITLE_PREFIX):
            initiative.block_slug = initiative.title[len(TITLE_PREFIX):]
            initiative.save(update_fields=["block_slug"])


def noop_reverse(apps, schema_editor):
    # Reversing would strand the real field this migration exists to fill;
    # 0035's reverse (dropping the column) already undoes this.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0035_initiative_block_slug"),
    ]

    operations = [
        migrations.RunPython(backfill_block_slug, noop_reverse),
    ]
