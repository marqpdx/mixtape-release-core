from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from folio.models import Folio
from fundamentals.models import BaseContent
from groups.models import Group


class FolioSlugTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="slug_writer")
        self.other = get_user_model().objects.create_user(username="slug_other")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make(self, title="", sponsor=None, **kwargs):
        return Folio.objects.create(title=title, sponsor=sponsor or self.user,
                                    author=self.user, submitted_by=self.user, **kwargs)

    def test_basecontent_and_member_creation_mapping(self):
        response = self.client.post("/api/folio/folios", {"title": "The Quiet City", "slug": "override"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["slug"], "the-quiet-city")
        row = Folio.objects.get(pk=response.data["id"])
        self.assertIsInstance(row, BaseContent)
        self.assertEqual(row.sponsor, self.user)
        self.assertEqual(row.author, self.user)
        self.assertEqual(row.submitted_by, self.user)
        self.assertEqual(Folio._meta.get_field("title").max_length, 255)

    def test_different_members_share_slug_duplicates_in_one_scope_get_counters(self):
        first = self.make("Same")
        second = self.make("Same")
        third = self.make("Same")
        different = self.make("Same", sponsor=self.other)
        self.assertEqual([first.slug, second.slug, third.slug], ["same", "same-2", "same-3"])
        self.assertEqual(different.slug, "same")
        self.assertFalse(first.slug_exists("same-4"))

    def test_group_sponsor_has_its_own_scope_not_exposed_as_personal_folio(self):
        group = Group.objects.create(title="Writers", sponsor=self.user, author=self.user, submitted_by=self.user)
        personal = self.make("Same")
        grouped = self.make("Same", sponsor=group)
        grouped_again = self.make("Same", sponsor=group)
        self.assertEqual(personal.slug, grouped.slug)
        self.assertEqual(grouped_again.slug, "same-2")
        visible = {row["id"] for row in self.client.get("/api/folio/folios").data}
        self.assertIn(str(personal.pk), visible)
        self.assertNotIn(str(grouped.pk), visible)
        self.assertEqual(self.client.get(f"/api/folio/folios/{grouped.pk}/notes").status_code, 404)

    def test_full_255_character_titles_fit_shared_64_character_slug_field(self):
        title = "a" * 255
        first = self.make(title)
        second = self.make(title)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.title, title)
        self.assertEqual(second.title, title)
        self.assertEqual(first.slug, "a" * 64)
        self.assertEqual(second.slug, "a" * 62 + "-2")

    def test_database_enforces_scope_constraint(self):
        self.make("Same")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make("Other", slug="same", slug_is_custom=True)

    def test_placeholder_promotes_once_with_history_via_title_api(self):
        row = self.make()
        old = row.slug
        self.assertTrue(old.startswith("untitled---"))
        response = self.client.patch(f"/api/folio/folios/{row.pk}", {"title": "The Quiet City"}, format="json")
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.slug, "the-quiet-city")
        self.assertIn(old, row.slug_history)
        self.assertIn(old, response.data["slug_history"])
        self.client.patch(f"/api/folio/folios/{row.pk}", {"title": "Different"}, format="json")
        row.refresh_from_db()
        self.assertEqual(row.slug, "the-quiet-city")

    def test_non_ascii_title_keeps_placeholder_without_losing_title(self):
        row = self.make("東京")
        self.assertEqual(row.title, "東京")
        self.assertTrue(row.slug.startswith("untitled---"))

    def test_personal_scope_is_not_author_scope(self):
        row = self.make("Private", sponsor=self.other)
        self.assertEqual(self.client.get(f"/api/folio/folios/{row.pk}/notes").status_code, 404)
        listed = self.client.get("/api/folio/folios")
        self.assertNotIn(str(row.pk), {item["id"] for item in listed.data})


class FolioSponsorMigrationTests(TransactionTestCase):
    def test_replacement_maps_legacy_creator_and_scopes_duplicate_titles(self):
        before = [("folio", "0004_alter_folionote_confirmed_shape_and_more")]
        after = [("folio", "0005_folio_slug")]
        executor = MigrationExecutor(connection)
        executor.migrate(before)
        try:
            state = executor.loader.project_state(before).apps
            old = state.get_model("folio", "Folio")
            app, model = get_user_model()._meta.app_label, get_user_model()._meta.model_name
            # Only Folio is migrated backward; the User table keeps its current schema.
            User = get_user_model()
            one = User.objects.create_user(username="legacy_one")
            two = User.objects.create_user(username="legacy_two")
            rows = [old.objects.create(title=title, created_by_id=owner.pk)
                    for title, owner in [("Same", one), ("Same", one), ("Same", two), ("", one)]]
            ids = [row.pk for row in rows]
            MigrationExecutor(connection).migrate(after)
            current = Folio.objects.in_bulk(ids)
            self.assertEqual(set(current), set(ids))
            self.assertEqual({current[ids[0]].slug, current[ids[1]].slug}, {"same", "same-2"})
            self.assertEqual(current[ids[2]].slug, "same")
            self.assertTrue(current[ids[3]].slug.startswith("untitled---"))
            for index, owner in enumerate([one, one, two, one]):
                row = current[ids[index]]
                self.assertEqual(row.sponsor_object_id, owner.pk)
                self.assertEqual(row.author_id, owner.pk)
                self.assertEqual(row.submitted_by_id, owner.pk)
                self.assertEqual(row.sponsor_content_type.model, model)
            self.assertNotIn("created_by", {field.name for field in Folio._meta.fields})
        finally:
            MigrationExecutor(connection).migrate(after)
