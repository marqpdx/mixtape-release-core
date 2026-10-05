# storyboard/tests/test_api.py
#
# API-level coverage for the Phase 5 acceptance subset, author-only
# authorization (build-handoff §2a), and the tree-constraint errors
# surfacing as clean 400s rather than 500s.

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from storyboard.models import Storyboard, StoryboardItem

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
