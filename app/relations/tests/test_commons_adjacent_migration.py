from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase


class CommonsAdjacentRelationshipTypeMigrationTests(SimpleTestCase):
    # See test_commons_migration.py for why MigrationExecutor, not
    # TransactionTestCase's global flush.
    databases = {"default"}

    migrate_from = [("relations", "0008_add_commons_relation_types")]
    migrate_to = [("relations", "0009_add_commons_adjacent_relation_type")]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self._migrate(self.migrate_to)
        super().tearDown()

    def test_seed_migration_applies_and_reverses_cleanly(self):
        old_apps = self._migrate(self.migrate_from)
        OldRelationshipType = old_apps.get_model("relations", "RelationshipType")
        self.assertFalse(OldRelationshipType.objects.filter(slug="adjacent").exists())

        new_apps = self._migrate(self.migrate_to)
        RelationshipType = new_apps.get_model("relations", "RelationshipType")
        adjacent = RelationshipType.objects.get(slug="adjacent")
        self.assertEqual(adjacent.domain, "commons")
        self.assertFalse(adjacent.is_directed)
        self.assertEqual(adjacent.label, "Adjacent to")
        self.assertEqual(adjacent.inverse_label, "Adjacent to")

        reversed_apps = self._migrate(self.migrate_from)
        ReversedRelationshipType = reversed_apps.get_model("relations", "RelationshipType")
        self.assertFalse(
            ReversedRelationshipType.objects.filter(slug="adjacent").exists()
        )
