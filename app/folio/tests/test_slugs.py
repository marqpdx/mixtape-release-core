from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from folio.models import Folio


class FolioSlugTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="slug_writer")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_slug_is_readable_stable_and_not_client_writable(self):
        response = self.client.post("/api/folio/folios", {"title": "The Quiet City", "slug": "override"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["slug"], "the-quiet-city")
        folio = Folio.objects.get(pk=response.data["id"])
        folio.title = "A Different Title"
        folio.save(update_fields=["title", "updated_at"])
        folio.refresh_from_db()
        self.assertEqual(folio.slug, "the-quiet-city")
        listed = self.client.get("/api/folio/folios")
        self.assertEqual(listed.data[0]["slug"], "the-quiet-city")

    def test_duplicate_empty_non_ascii_and_long_titles(self):
        first = Folio.objects.create(title="Same", created_by=self.user)
        second = Folio.objects.create(title="Same", created_by=self.user)
        self.assertEqual(first.slug, "same")
        self.assertNotEqual(first.slug, second.slug)
        self.assertTrue(second.slug.startswith("same-"))
        blank = Folio.objects.create(title="", created_by=self.user)
        other = Folio.objects.create(title="東京", created_by=self.user)
        self.assertTrue(blank.slug)
        self.assertNotEqual(blank.slug, other.slug)
        long = Folio.objects.create(title="a" * 255, created_by=self.user)
        self.assertLessEqual(len(long.slug), 200)

    def test_uuid_shaped_title_cannot_shadow_a_legacy_link(self):
        original = Folio.objects.create(title="Original", created_by=self.user)
        named = Folio.objects.create(title=str(original.pk), created_by=self.user)
        self.assertNotEqual(named.slug, str(original.pk))
        self.assertTrue(named.slug.startswith("folio-"))

    def test_slug_does_not_grant_access_to_another_writers_notes(self):
        other = get_user_model().objects.create_user(username="slug_other")
        folio = Folio.objects.create(title="Private", created_by=other)
        self.assertEqual(self.client.get(f"/api/folio/folios/{folio.id}/notes").status_code, 404)
        self.assertNotIn(str(folio.id), {row["id"] for row in self.client.get("/api/folio/folios").data})


class FolioSlugBackfillTests(TransactionTestCase):
    def test_existing_titles_backfill_uniquely_without_changing_identity(self):
        before = [("folio", "0004_alter_folionote_confirmed_shape_and_more")]
        after = [("folio", "0005_folio_slug")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            historical = executor.loader.project_state(before).apps.get_model("folio", "Folio")
            ids = [historical.objects.create(title=title).pk for title in ("The Quiet City", "The Quiet City", "", "東京")]
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            migrated = executor.loader.project_state(after).apps.get_model("folio", "Folio")
            rows = list(migrated.objects.filter(pk__in=ids))
            self.assertEqual({row.pk for row in rows}, set(ids))
            self.assertEqual(len({row.slug for row in rows}), 4)
            self.assertTrue(all(row.slug and len(row.slug) <= 200 for row in rows))
            self.assertEqual(sorted(row.title for row in rows), sorted(["The Quiet City", "The Quiet City", "", "東京"]))
        finally:
            MigrationExecutor(connection).migrate(after)
