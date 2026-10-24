"""Stable Folio web URLs. CTO review required before production deployment."""
import uuid

from django.db import migrations, models
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Folio = apps.get_model("folio", "Folio")
    db = schema_editor.connection.alias
    used = set()
    for folio in Folio.objects.using(db).order_by("created_at", "id").iterator():
        base = slugify(folio.title)[:160] or "folio"
        try:
            uuid.UUID(base)
        except ValueError:
            pass
        else:
            base = f"folio-{base}"
        candidate = base
        if candidate in used:
            candidate = f"{base}-{folio.pk.hex}"
        # Also handle a title deliberately equal to a generated collision slug.
        counter = 1
        while candidate in used:
            candidate = f"{base}-{folio.pk.hex}-{counter}"
            counter += 1
        used.add(candidate)
        Folio.objects.using(db).filter(pk=folio.pk).update(slug=candidate)


class Migration(migrations.Migration):
    dependencies = [("folio", "0004_alter_folionote_confirmed_shape_and_more")]
    operations = [
        migrations.AddField(
            model_name="folio", name="slug",
            field=models.SlugField(max_length=200, null=True, editable=False, db_index=False),
        ),
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="folio", name="slug",
            field=models.SlugField(max_length=200, unique=True, editable=False),
        ),
    ]
