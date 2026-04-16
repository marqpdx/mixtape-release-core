# curation/migrations/0002_migrate_library_contentplacements.py
#
# CP5 data migration — carry forward ContentPlacement rows that have
# stackroom.Library as their target.
#
# Why this exists:
#   publish_service.py previously created ContentPlacement rows with
#   target_content_type = Library (stackroom) for the "shelves" publish
#   destination. CP5 switches the shelf model to curation.Collection.
#   Any existing rows would become orphaned under the new query.
#
#   This migration:
#     1. Finds all stackroom.Library records that are ContentPlacement targets
#     2. Creates a corresponding curation.Collection for each (preserving UUID)
#     3. Re-points those ContentPlacement rows at the new Collection
#
#   Safe to run even if no such rows exist — it short-circuits immediately.
#
# Dependency: must run after curation 0001 (Collection model exists) and
# while stackroom is still in INSTALLED_APPS (Library model accessible).

from django.db import migrations


def migrate_library_placements(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentPlacement = apps.get_model('publishing', 'ContentPlacement')

    # Guard: if stackroom.Library isn't registered, nothing to do
    try:
        library_ct = ContentType.objects.get(app_label='stackroom', model='library')
    except ContentType.DoesNotExist:
        return

    Library = apps.get_model('stackroom', 'Library')
    Collection = apps.get_model('curation', 'Collection')
    collection_ct = ContentType.objects.get_for_model(Collection)

    # Find Library UUIDs that are actually referenced by ContentPlacement rows
    referenced_ids = ContentPlacement.objects.filter(
        target_content_type=library_ct,
    ).values_list('target_object_id', flat=True).distinct()

    if not referenced_ids:
        return

    libraries = Library.objects.filter(id__in=referenced_ids)

    for lib in libraries:
        # Create a Collection preserving the same UUID so target_object_id
        # rows don't need updating — only the content_type changes
        Collection.objects.get_or_create(
            id=lib.id,
            defaults=dict(
                title=lib.title,
                summary=getattr(lib, 'summary', '') or '',
                body=getattr(lib, 'body', '') or '',
                visibility=getattr(lib, 'visibility', 'private'),
                scope=getattr(lib, 'scope', 'general'),
                author_id=lib.author_id,
                author_name=getattr(lib, 'author_name', '') or '',
                submitted_by_id=lib.submitted_by_id,
                slug=lib.slug,
                sponsor_content_type_id=lib.sponsor_content_type_id,
                sponsor_object_id=lib.sponsor_object_id,
            ),
        )

    # Re-point all matching ContentPlacement rows to the Collection content type
    ContentPlacement.objects.filter(
        target_content_type=library_ct,
    ).update(target_content_type=collection_ct)


def reverse_migrate(apps, schema_editor):
    # Not reversible — Library records may no longer exist at this point
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('curation', '0001_initial'),
        ('publishing', '0005_contentplacement_order_index'),
        ('stackroom', '0016_stackroomsyncstate'),
    ]

    operations = [
        migrations.RunPython(migrate_library_placements, reverse_code=reverse_migrate),
    ]
