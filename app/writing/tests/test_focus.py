# Focus-Centered Writing ADR, Phase 2 (FCW-5): Focus model + endpoints.
# Covers the Phase 2 acceptance-criteria subset that's backend-testable now
# (ADR §9 items 4-6 depend on frontend state; this covers the server side
# that backs them) plus the §8 edge case of the Focus's target being deleted.

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from writing.models import Focus, Issue

User = get_user_model()


def _create_issue(*, user, title="Issue 1"):
    user_ct = ContentType.objects.get_for_model(user)
    return Issue.objects.create(
        title=title, sponsor_content_type=user_ct, sponsor_object_id=user.pk,
    )


class FocusServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="writer", email="writer@example.com", password="testpass123",
        )
        self.issue = _create_issue(user=self.user)

    def test_create_focus_defaults_to_publish_and_active(self):
        issue_ct = ContentType.objects.get_for_model(Issue)
        focus = Focus.objects.create(
            user=self.user,
            target_content_type=issue_ct,
            target_object_id=self.issue.id,
        )
        self.assertEqual(focus.verb, Focus.Verb.PUBLISH)
        self.assertEqual(focus.status, Focus.Status.ACTIVE)
        self.assertEqual(focus.target, self.issue)

    def test_deleting_target_issue_abandons_active_focus(self):
        issue_ct = ContentType.objects.get_for_model(Issue)
        focus = Focus.objects.create(
            user=self.user, target_content_type=issue_ct, target_object_id=self.issue.id,
        )
        self.issue.delete()
        focus.refresh_from_db()
        self.assertEqual(focus.status, Focus.Status.ABANDONED)
        self.assertIsNotNone(focus.resolved_at)

    def test_deleting_issue_does_not_touch_resolved_focus(self):
        issue_ct = ContentType.objects.get_for_model(Issue)
        focus = Focus.objects.create(
            user=self.user, target_content_type=issue_ct, target_object_id=self.issue.id,
            status=Focus.Status.RESOLVED,
        )
        self.issue.delete()
        focus.refresh_from_db()
        self.assertEqual(focus.status, Focus.Status.RESOLVED)


class FocusAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="writer2", email="writer2@example.com", password="testpass123",
            is_superuser=True,
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="testpass123",
            is_superuser=True,
        )
        self.issue = _create_issue(user=self.user, title="Issue 1")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_focus(self):
        return self.client.post(
            "/api/writing/focuses",
            {"object_type": "issue", "object_id": str(self.issue.id)},
            format="json",
        )

    def test_create_and_list_focus(self):
        response = self._create_focus()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["verb"], "publish")
        self.assertEqual(response.data["object_type"], "issue")
        self.assertEqual(response.data["status"], "active")

        list_response = self.client.get("/api/writing/focuses")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["id"], response.data["id"])

    def test_cannot_create_focus_on_issue_you_cannot_manage(self):
        other_issue = _create_issue(user=self.other_user, title="Not yours")
        response = self.client.post(
            "/api/writing/focuses",
            {"object_type": "issue", "object_id": str(other_issue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_focus_deep_link(self):
        focus_id = self._create_focus().data["id"]
        response = self.client.get(f"/api/writing/focuses/{focus_id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], focus_id)

    def test_another_user_cannot_see_your_focus(self):
        focus_id = self._create_focus().data["id"]
        other_client = APIClient()
        other_client.force_authenticate(user=self.other_user)
        response = other_client.get(f"/api/writing/focuses/{focus_id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_state_for_exact_resume(self):
        focus_id = self._create_focus().data["id"]
        response = self.client.patch(
            f"/api/writing/focuses/{focus_id}/state",
            {"state": {"selected_piece_id": "abc-123", "open_tool": "edit"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["state"]["open_tool"], "edit")

        refetched = self.client.get(f"/api/writing/focuses/{focus_id}")
        self.assertEqual(refetched.data["state"]["selected_piece_id"], "abc-123")

    def test_resolve_focus(self):
        focus_id = self._create_focus().data["id"]
        response = self.client.post(f"/api/writing/focuses/{focus_id}/resolve")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "resolved")
        self.assertIsNotNone(response.data["resolved_at"])

        # Resolved Focus drops out of the active list
        list_response = self.client.get("/api/writing/focuses")
        self.assertEqual(len(list_response.data), 0)

    def test_cannot_resolve_already_resolved_focus(self):
        focus_id = self._create_focus().data["id"]
        self.client.post(f"/api/writing/focuses/{focus_id}/resolve")
        second = self.client.post(f"/api/writing/focuses/{focus_id}/resolve")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_object_type_is_rejected(self):
        response = self.client.post(
            "/api/writing/focuses",
            {"object_type": "writing_piece", "object_id": str(self.issue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
