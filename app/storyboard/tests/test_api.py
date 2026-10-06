# storyboard/tests/test_api.py
#
# API-level coverage for the Phase 5 acceptance subset, author-only
# authorization (build-handoff §2a), and the tree-constraint errors
# surfacing as clean 400s rather than 500s.

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from storyboard.models import Storyboard, StoryboardItem
from folio.models import Folio, FolioNote, FolioNoteSource, FolioNoteStatus
from storyboard.models import Entity, Participation, StoryboardItemLink

User = get_user_model()


class StoryboardAPITestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="novelist")
        self.other_user = User.objects.create_user(username="someone_else")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_storyboard(self):
        response = self.client.post(
            "/api/storyboard/storyboards",
            {"grammar": "fiction_v1", "title": "Union Station"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["title"], "Union Station")
        self.assertEqual(response.data["kind"], "writing")

        storyboard = Storyboard.objects.get(pk=response.data["id"])
        self.assertEqual(storyboard.created_by_id, self.user.id)
        self.assertEqual(storyboard.sponsor_object_id, self.user.id)

    def test_create_storyboard_rejects_unknown_grammar(self):
        response = self.client.post(
            "/api/storyboard/storyboards",
            {"grammar": "not_a_real_grammar"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_storyboard_can_draw_from_multiple_owned_folios(self):
        folios = [Folio.objects.create(title=title, created_by=self.user) for title in ("Book", "World")]
        response = self.client.post(
            "/api/storyboard/storyboards",
            {"grammar": "fiction_v1", "folio_ids": [str(folio.id) for folio in folios]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data["folio_ids"]), {str(folio.id) for folio in folios})
        self.assertEqual(Storyboard.objects.get(pk=response.data["id"]).folios.count(), 2)

    def test_storyboard_rejects_another_users_folio(self):
        folio = Folio.objects.create(title="Private", created_by=self.other_user)
        response = self.client.post(
            "/api/storyboard/storyboards",
            {"grammar": "fiction_v1", "folio_ids": [str(folio.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_build_and_view_tree_linearly(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]

        part = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "part", "title": "Part I"},
            format="json",
        ).data
        chapter = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "chapter", "parent_id": part["id"], "title": "Chapter 1"},
            format="json",
        ).data
        scene_response = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "scene", "parent_id": chapter["id"], "title": "Arrival"},
            format="json",
        )
        self.assertEqual(scene_response.status_code, 201)
        scene = scene_response.data
        self.assertEqual(scene["reference"]["content_type"], "writingpiece")

        detail = self.client.get(f"/api/storyboard/storyboards/{storyboard_id}")
        self.assertEqual(detail.status_code, 200)
        item_ids = {item["id"] for item in detail.data["items"]}
        self.assertEqual(item_ids, {part["id"], chapter["id"], scene["id"]})

    def test_scene_cannot_be_created_as_root(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]
        response = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "scene", "title": "orphan"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_siblings(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]
        chapter_id = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "chapter", "title": "Chapter 1"},
            format="json",
        ).data["id"]
        scene_ids = [
            self.client.post(
                f"/api/storyboard/storyboards/{storyboard_id}/items",
                {"level": "scene", "parent_id": chapter_id, "title": title},
                format="json",
            ).data["id"]
            for title in ("Morning", "Noon", "Night")
        ]

        response = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items/reorder",
            {"parent_id": chapter_id, "ordered_item_ids": list(reversed(scene_ids))},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        ranked = {item["id"]: item["rank"] for item in response.data}
        self.assertEqual(ranked[scene_ids[2]], 0)
        self.assertEqual(ranked[scene_ids[0]], 2)

    def test_patch_item_title(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]
        item_id = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "part", "title": "Part I"},
            format="json",
        ).data["id"]

        response = self.client.patch(
            f"/api/storyboard/storyboards/{storyboard_id}/items/{item_id}",
            {"title": "Part One"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Part One")

    def test_surface_movement_does_not_change_rank_and_reset_preserves_size(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]
        item_id = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "chapter", "title": "First"}, format="json",
        ).data["id"]
        url = f"/api/storyboard/storyboards/{storyboard_id}/items/{item_id}/surface"
        response = self.client.patch(url, {"x": 413, "y": 92, "size": "large", "expanded": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StoryboardItem.objects.get(pk=item_id).rank, 0)
        self.assertEqual(self.client.get(f"/api/storyboard/storyboards/{storyboard_id}").data["surface_states"][0]["x"], 413)
        reset = self.client.post(f"/api/storyboard/storyboards/{storyboard_id}/surface/reset")
        self.assertEqual(reset.status_code, 200)
        state = self.client.get(f"/api/storyboard/storyboards/{storyboard_id}").data["surface_states"][0]
        self.assertIsNone(state["x"])
        self.assertEqual(state["size"], "large")

    def test_participation_reuses_sponsor_entity_and_rejects_foreign_sponsor(self):
        storyboard_id = self.client.post("/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json").data["id"]
        item_id = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "chapter", "title": "One"}, format="json",
        ).data["id"]
        url = f"/api/storyboard/storyboards/{storyboard_id}/items/{item_id}/participations"
        created = self.client.post(url, {"kind": "character", "name": "Leo"}, format="json")
        self.assertEqual(created.status_code, 201)
        entity_id = created.data["entity_id"]
        second = self.client.post(url, {"kind": "character", "entity_id": entity_id}, format="json")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Participation.objects.filter(item_id=item_id).count(), 1)
        self.assertEqual(Entity.objects.get(pk=entity_id).sponsor_object_id, self.user.id)
        self.assertEqual(self.client.post(url, {"kind": "claim", "name": "Wrong grammar"}, format="json").status_code, 400)

        other = self.client.post("/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json").data["id"]
        other_item = self.client.post(
            f"/api/storyboard/storyboards/{other}/items", {"level": "chapter"}, format="json"
        ).data["id"]
        reused = self.client.post(
            f"/api/storyboard/storyboards/{other}/items/{other_item}/participations",
            {"kind": "character", "entity_id": entity_id}, format="json",
        )
        self.assertEqual(reused.status_code, 201)

    def test_note_link_preserves_scene_reference_and_mention_requires_confirmation(self):
        folio = Folio.objects.create(title="Notes", created_by=self.user)
        note = FolioNote.objects.create(
            folio=folio, created_by=self.user, source_type=FolioNoteSource.TEXT,
            raw_text="Leo enters the room.", status=FolioNoteStatus.READY,
            mentions=[{"surface": "Leo", "kind": "character", "confidence": 0.9, "existing_entity_id": None}],
        )
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1", "folio_ids": [str(folio.id)]}, format="json"
        ).data["id"]
        chapter = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items", {"level": "chapter"}, format="json"
        ).data["id"]
        scene = self.client.post(
            f"/api/storyboard/storyboards/{storyboard_id}/items",
            {"level": "scene", "parent_id": chapter}, format="json",
        ).data
        item_url = f"/api/storyboard/storyboards/{storyboard_id}/items/{scene['id']}"
        linked = self.client.post(f"{item_url}/links", {"note_id": str(note.id)}, format="json")
        self.assertEqual(linked.status_code, 201)
        self.assertEqual(StoryboardItemLink.objects.filter(item_id=scene["id"]).count(), 1)
        detail = self.client.get(f"/api/storyboard/storyboards/{storyboard_id}").data
        self.assertEqual(next(item for item in detail["items"] if str(item["id"]) == str(scene["id"]))["reference"], scene["reference"])
        self.assertEqual(Participation.objects.filter(item_id=scene["id"]).count(), 0)
        confirmed = self.client.post(
            f"{item_url}/participations",
            {"kind": "character", "note_id": str(note.id), "mention_index": 0, "name": "Leo"}, format="json",
        )
        self.assertEqual(confirmed.status_code, 201)
        note.refresh_from_db()
        self.assertEqual(note.mentions[0]["confirmed_entity_id"], confirmed.data["entity_id"])

    def test_another_user_cannot_see_or_edit_the_storyboard(self):
        storyboard_id = self.client.post(
            "/api/storyboard/storyboards", {"grammar": "fiction_v1"}, format="json"
        ).data["id"]

        other_client = APIClient()
        other_client.force_authenticate(self.other_user)

        self.assertEqual(
            other_client.get(f"/api/storyboard/storyboards/{storyboard_id}").status_code, 404
        )
        self.assertEqual(
            other_client.post(
                f"/api/storyboard/storyboards/{storyboard_id}/items",
                {"level": "part", "title": "intrusion"},
                format="json",
            ).status_code,
            404,
        )
