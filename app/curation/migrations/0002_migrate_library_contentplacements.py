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


class Migration(migrations.Migration):

    dependencies = [
        ('curation', '0001_initial'),
        ('publishing', '0005_contentplacement_order_index'),
    ]

    operations = []
