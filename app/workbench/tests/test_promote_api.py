from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from workbench.models import WorkingItemStatus
from writing.models import WorkingDocument, WritingPiece

from .helpers import create_group, create_working_item


User = get_user_model()


class WorkingItemPromoteAPITests(APITestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="promote_super",
            email="promote_super@example.com",
            password="testpass123",
        )
        self.group_admin = User.objects.create_user(
            username="promote_admin",
            email="promote_admin@example.com",
            password="testpass123",
        )
        self.group = create_group(
            sponsor_user=self.superuser,
            title="Promote Group",
            slug="promote-group",
        )

    def _auth_superuser(self):
        self.client.force_authenticate(self.superuser)

    def _promote(self, item_id, payload=None):
        return self.client.post(
            f"/api/groups/{self.group.slug}/workbench/working-items/{item_id}/promote",
            payload or {},
            format="json",
        )

    def test_promote_hard_gate_title_required(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="",
            status=WorkingItemStatus.READY,
            spellcheck_passed=True,
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["failures"][0]["gate"], "title_required")

    def test_promote_hard_gate_status_ready(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Needs Status",
            status=WorkingItemStatus.ASSEMBLING,
            spellcheck_passed=True,
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        gates = {failure["gate"] for failure in response.data["failures"]}
        self.assertIn("status_ready", gates)

    def test_promote_soft_gate_requires_override(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Soft Gate",
            status=WorkingItemStatus.READY,
            spellcheck_passed=False,
            body="promote body",
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["failures"][0]["gate"], "spellcheck")
        self.assertFalse(response.data["failures"][0]["hard"])

        override_response = self._promote(item.id, {"override_soft_gates": True})
        self.assertEqual(override_response.status_code, status.HTTP_201_CREATED)

    def test_promote_all_gates_pass_creates_writing_piece_and_working_document(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Ready Item",
            status=WorkingItemStatus.READY,
            spellcheck_passed=True,
            body="promote body",
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(WritingPiece.objects.filter(pk=response.data["writing_piece_id"]).exists())
        self.assertTrue(WorkingDocument.objects.filter(pk=response.data["working_document_id"]).exists())

        item.refresh_from_db()
        self.assertEqual(item.status, WorkingItemStatus.PROMOTED)
        self.assertIsNotNone(item.promoted_to_id)
        self.assertIsNotNone(item.promoted_at)

    def test_promote_already_promoted_blocked(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Already",
            status=WorkingItemStatus.PROMOTED,
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_promote_is_atomic_on_creation_failure(self):
        self._auth_superuser()
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Atomic",
            status=WorkingItemStatus.READY,
            spellcheck_passed=True,
            body="atomic body",
        )
        with patch("writing.models.WritingPiece.save", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._promote(item.id)

        item.refresh_from_db()
        self.assertEqual(item.status, WorkingItemStatus.READY)
        self.assertIsNone(item.promoted_to_id)

    def test_promote_non_superuser_rejected(self):
        self.client.force_authenticate(self.group_admin)
        item = create_working_item(
            group=self.group,
            author=self.superuser,
            title="Ready",
            status=WorkingItemStatus.READY,
            spellcheck_passed=True,
        )
        response = self._promote(item.id)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
