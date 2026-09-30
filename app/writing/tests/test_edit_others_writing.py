from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from groups.models import Group, GroupMembership
from groups.services.permissions import DECORATOR_PERMISSIONS, PermissionService
from writing.models import WritingPiece


User = get_user_model()


class EditOthersWritingTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="piece_author", email="author@example.com", password="testpass123"
        )
        self.editor = User.objects.create_user(
            username="group_editor", email="editor@example.com", password="testpass123"
        )
        self.group = Group.objects.create(
            title="Editorial Group", slug="editorial-group", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.author.id,
        )
        self.other_group = Group.objects.create(
            title="Other Group", slug="other-editorial-group", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.author.id,
        )
        self.piece = self._piece(self.group, "Shared Draft")
        self.other_piece = self._piece(self.other_group, "Other Draft")
        self.client = APIClient()

    def _piece(self, group, title):
        piece = WritingPiece(
            author=self.author,
            author_name=self.author.username,
            title=title,
            body_json={"type": "doc", "content": [{"type": "paragraph"}]},
            status="draft",
        )
        piece.set_sponsor(group)
        piece.set_submitted_by(self.author)
        piece.save()
        return piece

    def _role(self, role):
        GroupMembership.objects.create(
            group=self.group,
            member_content_type=ContentType.objects.get_for_model(User),
            member_object_id=self.editor.id,
            roles=[role],
            is_active=True,
            is_pending=False,
        )
        self.client.force_authenticate(user=self.editor)

    def test_role_permission_is_group_scoped_and_not_in_manage_writing_decorator(self):
        self._role("steward")
        self.assertTrue(PermissionService.can_user_perform_action(
            self.editor, "edit_others_writing", group_slug=self.group.slug
        ))
        self.assertFalse(PermissionService.can_user_perform_action(
            self.editor, "edit_others_writing", group_slug=self.other_group.slug
        ))
        self.assertNotIn("edit_others_writing", DECORATOR_PERMISSIONS["can__ManageWriting"])

    def test_view_others_drafts_is_group_scoped_and_not_in_manage_writing_decorator(self):
        self._role("steward")
        membership = GroupMembership.objects.get(group=self.group, member_object_id=self.editor.id)

        for role in ("steward", "admin", "owner"):
            with self.subTest(role=role):
                membership.roles = [role]
                membership.save(update_fields=["roles"])
                self.assertTrue(PermissionService.can_user_perform_action(
                    self.editor, "view_others_writing_drafts", group_slug=self.group.slug
                ))
                self.assertFalse(PermissionService.can_user_perform_action(
                    self.editor, "view_others_writing_drafts", group_slug=self.other_group.slug
                ))

        for role in ("coordinator", "member"):
            with self.subTest(role=role):
                membership.roles = [role]
                membership.save(update_fields=["roles"])
                self.assertFalse(PermissionService.can_user_perform_action(
                    self.editor, "view_others_writing_drafts", group_slug=self.group.slug
                ))

        self.assertNotIn("view_others_writing_drafts", DECORATOR_PERMISSIONS["can__ManageWriting"])

    def test_steward_can_edit_another_authors_group_piece_but_not_delete_it(self):
        self._role("steward")
        url = f"/api/writing/pieces/{self.piece.id}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"title": "Reviewed Draft"}, format="json").status_code, 200)
        self.piece.refresh_from_db()
        self.assertEqual(self.piece.title, "Reviewed Draft")
        self.assertEqual(self.client.delete(url).status_code, 403)
        self.assertTrue(WritingPiece.objects.filter(pk=self.piece.pk).exists())

        working_copy_url = f"{url}/working-copy"
        self.assertEqual(self.client.get(working_copy_url).status_code, 200)
        self.assertEqual(self.client.put(
            working_copy_url,
            {"title": "Reviewed Draft", "body_json": {"type": "doc", "content": [{"type": "paragraph"}]}},
            format="json",
        ).status_code, 200)
        self.assertEqual(self.client.put(f"{url}/tags", {"tag_ids": []}, format="json").status_code, 200)
        self.assertEqual(self.client.put(f"{url}/categories", {"category_ids": []}, format="json").status_code, 200)

    def test_edit_writing_alone_does_not_allow_cross_author_edit(self):
        self._role("coordinator")
        url = f"/api/writing/pieces/{self.piece.id}"
        self.assertTrue(PermissionService.can_user_perform_action(
            self.editor, "edit_writing", group_slug=self.group.slug
        ))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.patch(url, {"title": "No"}, format="json").status_code, 403)
        self.assertEqual(self.client.put(f"{url}/working-copy", {"title": "No"}, format="json").status_code, 403)
        self.assertEqual(self.client.put(f"{url}/tags", {"tag_ids": []}, format="json").status_code, 403)

    def test_permission_does_not_cross_group_boundary(self):
        self._role("steward")
        url = f"/api/writing/pieces/{self.other_piece.id}"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.patch(url, {"title": "No"}, format="json").status_code, 403)

    def test_author_can_still_edit_own_piece(self):
        self.client.force_authenticate(user=self.author)
        url = f"/api/writing/pieces/{self.piece.id}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"title": "Author Edit"}, format="json").status_code, 200)

    @patch("switchboard.api.views.celery_app.send_task")
    def test_steward_can_generate_and_confirm_summaries(self, send_task):
        self._role("steward")
        self.editor.user_permissions.add(Permission.objects.get(codename="approve_cloud_dispatch"))
        self.piece.body_json = {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "A careful account of a real project and its results. " * 40}]}],
        }
        self.piece.save(update_fields=["body_json", "updated_at"])

        summaries_url = f"/api/atelier/{self.piece.slug}/summaries/"
        self.assertEqual(self.client.get(summaries_url).status_code, 200)
        self.assertEqual(self.client.patch(
            summaries_url, {"public_synopsis": "A reviewed public summary."}, format="json"
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f"/api/atelier/{self.piece.slug}/summaries/confirm/",
            {"types": ["public_synopsis"]}, format="json",
        ).status_code, 200)

        for kind in ("public", "linkedin"):
            response = self.client.post(
                f"/api/switchboard/agent/synopsis/{kind}",
                {"piece_id": str(self.piece.id), "surface": "writing"},
                format="json",
            )
            self.assertEqual(response.status_code, 202)
        self.assertEqual(send_task.call_count, 2)

    @patch("switchboard.api.views.celery_app.send_task")
    def test_coordinator_cannot_access_another_authors_summaries(self, send_task):
        self._role("coordinator")
        self.editor.user_permissions.add(Permission.objects.get(codename="approve_cloud_dispatch"))
        url = f"/api/atelier/{self.piece.slug}/summaries/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {"public_synopsis": "No"}, format="json").status_code, 404)
        self.assertEqual(self.client.post(
            f"/api/atelier/{self.piece.slug}/summaries/confirm/", {"types": ["public_synopsis"]}, format="json"
        ).status_code, 404)
        for kind in ("public", "linkedin"):
            self.assertEqual(self.client.post(
                f"/api/switchboard/agent/synopsis/{kind}",
                {"piece_id": str(self.piece.id), "surface": "writing"}, format="json",
            ).status_code, 404)
        send_task.assert_not_called()
