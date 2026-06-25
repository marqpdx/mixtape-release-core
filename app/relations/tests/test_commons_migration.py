from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase


class CommonsRelationshipTypeMigrationTests(SimpleTestCase):
    # MigrationExecutor owns the transaction boundaries here. Avoid
    # TransactionTestCase's global flush: legacy cross-app database FKs make
    # Django's project-wide TRUNCATE invalid on PostgreSQL.
    databases = {"default"}

    migrate_from = [("relations", "0007_add_circle_relation_types")]
    migrate_to = [("relations", "0008_add_commons_relation_types")]
    commons_slugs = {
        "presence",
        "continues",
        "origin",
        "context",
        "continuation",
        "parallel",
    }

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
        self.assertFalse(
            OldRelationshipType.objects.filter(slug__in=self.commons_slugs).exists()
        )

        new_apps = self._migrate(self.migrate_to)
        RelationshipType = new_apps.get_model("relations", "RelationshipType")
        rows = {
            row.slug: row
            for row in RelationshipType.objects.filter(slug__in=self.commons_slugs)
        }
        self.assertEqual(set(rows), self.commons_slugs)
        self.assertTrue(rows["presence"].uses_lifecycle)
        self.assertTrue(rows["continues"].allows_position)

        reversed_apps = self._migrate(self.migrate_from)
        ReversedRelationshipType = reversed_apps.get_model(
            "relations", "RelationshipType"
        )
        self.assertFalse(
            ReversedRelationshipType.objects.filter(
                slug__in=self.commons_slugs
            ).exists()
        )
