from django.contrib.contenttypes.models import ContentType
from rest_framework import status
from rest_framework.test import APITestCase

from workbench.models import WorkingItemMembership, WorkingItemStatus
from writing.models import WritingPiece

from .helpers import (
    add_group_member,
    body_json,
    create_group,
    create_seed,
    create_working_item,
)
from django.contrib.auth import get_user_model


User = get_user_model()


class WorkingItemsAPITests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="wb_super",
            email="wb_super@example.com",
            password="testpass123",
        )
        self.group_admin = User.objects.create_user(
            username="wb_admin",
            email="wb_admin@example.com",
            password="testpass123",
        )
        self.outsider = User.objects.create_user(
            username="wb_outsider",
            email="wb_outsider@example.com",
            password="testpass123",
        )

        self.group = create_group(
            sponsor_user=self.superuser,
            title="Workbench Group",
            slug="workbench-group",
        )
        self.other_group = create_group(
            sponsor_user=self.superuser,
            title="Other Group",
            slug="workbench-other-group",
        )
        add_group_member(group=self.group, user=self.group_admin, roles=["admin"])

        self.seed = create_seed(author=self.group_admin, body_text="First seed body")
        self.seed_ct = ContentType.objects.get_for_model(self.seed)

    def _auth_superuser(self):
        self.client.force_authenticate(self.superuser)

    def _auth_group_admin(self):
        self.client.force_authenticate(self.group_admin)

    def test_list_working_items_empty(self):
        self._auth_superuser()
        response = self.client.get(f"/api/groups/{self.group.slug}/workbench/working-items")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_list_returns_group_items_only_and_excludes_promoted_by_default(self):
        self._auth_superuser()
        visible = create_working_item(group=self.group, author=self.superuser, title="Visible")
        create_working_item(
            group=self.group,
            author=self.superuser,
            title="Promoted",
            status=WorkingItemStatus.PROMOTED,
        )
        create_working_item(group=self.other_group, author=self.superuser, title="Other Group")

        response = self.client.get(f"/api/groups/{self.group.slug}/workbench/working-items")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertEqual(ids, {str(visible.id)})

    def test_create_working_item_stitches_body_and_memberships(self):
        self._auth_superuser()
        response = self.client.post(
            f"/api/groups/{self.group.slug}/workbench/working-items",
            {
                "title": "Assembled",
                "pieces": [
                    {
                        "content_type_id": self.seed_ct.id,
                        "object_id": str(self.seed.id),
                        "position": 0,
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], WorkingItemStatus.ASSEMBLING)
        self.assertEqual(len(response.data["memberships"]), 1)
        text = response.data["body_json"]["content"][0]["content"][0]["text"]
        self.assertEqual(text, "First seed body")

    def test_create_missing_title_allowed(self):
        self._auth_superuser()
        response = self.client.post(
            f"/api/groups/{self.group.slug}/workbench/working-items",
            {"title": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "")

    def test_create_non_superuser_rejected(self):
        self._auth_group_admin()
        response = self.client.post(
            f"/api/groups/{self.group.slug}/workbench/working-items",
            {"title": "Nope"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_wrong_group_404(self):
        self._auth_superuser()
        item = create_working_item(group=self.other_group, author=self.superuser, title="Other")
        response = self.client.get(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_promoted_item_blocked(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Promoted",
            status=WorkingItemStatus.PROMOTED,
        )
        response = self.client.patch(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}",
            {"title": "Changed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        item.refresh_from_db()
        self.assertEqual(item.title, "Promoted")

    def test_delete_soft_deletes_and_hides_from_default_list(self):
        self._auth_superuser()
        item = create_working_item(group=self.group, author=self.superuser, title="To Delete")
        delete_response = self.client.delete(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}"
        )
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        item.refresh_from_db()
        self.assertEqual(item.status, WorkingItemStatus.ARCHIVED)
        self.assertIsNotNone(item.deleted_at)

        list_response = self.client.get(f"/api/groups/{self.group.slug}/workbench/working-items")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data, [])

    def test_autosave_body_sets_fork_lock_and_resets_spellcheck(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Autosave",
            spellcheck_passed=True,
        )
        response = self.client.patch(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/autosave",
            {"body_json": body_json("edited body")},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["body_editing_started"])
        self.assertFalse(response.data["spellcheck_passed"])
        self.assertEqual(response.data["auto_save_count"], 1)

    def test_autosave_title_only_does_not_set_fork_lock(self):
        self._auth_superuser()
        item = create_working_item(group=self.group, author=self.superuser, title="Autosave")
        response = self.client.patch(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/autosave",
            {"title": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["body_editing_started"])
        item.refresh_from_db()
        self.assertEqual(item.title, "Renamed")

    def test_autosave_promoted_item_blocked(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Done",
            status=WorkingItemStatus.PROMOTED,
        )
        response = self.client.patch(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/autosave",
            {"body_json": body_json("nope")},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_and_remove_piece_before_fork_lock(self):
        self._auth_superuser()
        item = create_working_item(group=self.group, author=self.superuser, title="Assembly")
        add_response = self.client.post(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/pieces",
            {"content_type_id": self.seed_ct.id, "object_id": str(self.seed.id)},
            format="json",
        )
        self.assertEqual(add_response.status_code, status.HTTP_201_CREATED)
        membership_id = add_response.data["id"]
        item.refresh_from_db()
        self.assertEqual(item.memberships.count(), 1)

        remove_response = self.client.delete(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/pieces/{membership_id}"
        )
        self.assertEqual(remove_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(item.memberships.count(), 0)

    def test_remove_piece_after_fork_lock_blocked(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Locked",
            body_editing_started=True,
        )
        membership = WorkingItemMembership.objects.create(
            working_item=item,
            piece_content_type=self.seed_ct,
            piece_object_id=self.seed.id,
            content_snapshot="First seed body",
            position=0,
        )
        response = self.client.delete(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}/pieces/{membership.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_promoted_item_cannot_be_deleted(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Promoted",
            status=WorkingItemStatus.PROMOTED,
        )
        response = self.client.delete(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_requests_are_rejected(self):
        response = self.client.get(f"/api/groups/{self.group.slug}/workbench/working-items")
        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})
