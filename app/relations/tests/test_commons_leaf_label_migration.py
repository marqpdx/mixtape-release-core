from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase


class CommonsLeafLabelMigrationTests(SimpleTestCase):
    # MigrationExecutor, as in test_commons_adjacent_migration.py.
    databases = {"default"}

    migrate_from = [("relations", "0009_add_commons_adjacent_relation_type")]
    migrate_to = [("relations", "0010_correct_commons_leaf_type_labels")]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self._migrate(self.migrate_to)
        super().tearDown()

    def test_labels_are_corrected_and_the_reverse_restores_them(self):
        old = self._migrate(self.migrate_from).get_model("relations", "RelationshipType")
        self.assertEqual(old.objects.get(slug="continues").valid_source_types, ["writing.Leaf"])

        new = self._migrate(self.migrate_to).get_model("relations", "RelationshipType")
        continues = new.objects.get(slug="continues")
        self.assertEqual(continues.valid_source_types, ["commons.Leaf"])
        self.assertEqual(continues.valid_target_types, ["commons.Leaf"])
        presence = new.objects.get(slug="presence")
        self.assertEqual(presence.valid_source_types, ["commons.Leaf"])
        self.assertEqual(presence.valid_target_types, ["users.CustomUser"])
        # Types outside the list are untouched.
        self.assertEqual(new.objects.get(slug="adjacent").valid_source_types, ["commons.CommonsItem", "tapestry.Place"])

        back = self._migrate(self.migrate_from).get_model("relations", "RelationshipType")
        self.assertEqual(back.objects.get(slug="continues").valid_source_types, ["writing.Leaf"])
