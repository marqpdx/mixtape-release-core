# initiatives/migrations/0032_backfill_initiative_surface.py
#
# ADR-0064 D3: every existing Initiative belongs to Atrium. Runs once, right
# after 0031 adds the (nullable) surface field, so no Initiative is ever
# without a Surface outside this one migration's transaction.

from django.db import migrations


def backfill_to_atrium(apps, schema_editor):
    Initiative = apps.get_model("initiatives", "Initiative")
    SurfaceProfile = apps.get_model("surfaces", "SurfaceProfile")
    atrium = SurfaceProfile.objects.get(slug="atrium")
    Initiative.objects.filter(surface__isnull=True).update(surface=atrium)


def noop_reverse(apps, schema_editor):
    # Reversing a backfill to null would strand every Initiative without a
    # Surface; 0031's reverse (dropping the column) already undoes this.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("initiatives", "0031_initiative_surface"),
    ]

    operations = [
        migrations.RunPython(backfill_to_atrium, noop_reverse),
    ]
