from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from groups.models.group import Group
from initiatives.models import ActionRun
from writing.models import WritingPiece, WritingSynopsis


User = get_user_model()


def _body_json(text: str) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


class WritingSynopsisActionTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="synopsis-author",
            email="author@example.com",
            password="testpass123",
        )
        article_text = " ".join(
            [
                "Careful software work keeps judgment with people while tools help with repetition."
                for _ in range(60)
            ]
        )
        self.piece = WritingPiece(
            author=self.author,
            author_name=self.author.username,
            title="A careful article",
            body_json=_body_json(article_text),
            status="draft",
            writing_kind="article",
        )
        self.piece.set_sponsor(self.author)
        self.piece.set_submitted_by(self.author)
        self.piece.save()
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    @patch("switchboard.api.views.celery_app.send_task")
    def test_public_synopsis_creates_governed_action_with_article_body(self, send_task):
        response = self.client.post(
            "/api/switchboard/agent/synopsis/public",
            {"piece_id": str(self.piece.id), "surface": "writing"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        action_run = ActionRun.objects.get(pk=response.json()["action_run_id"])
        self.assertEqual(action_run.tool_name, "writing.summarize")
        self.assertEqual(action_run.request_payload["piece_id"], str(self.piece.id))
        self.assertEqual(action_run.request_payload["summary_type"], "public_synopsis")
        task_kwargs = send_task.call_args.kwargs["kwargs"]
        self.assertGreater(len(task_kwargs["summarize_payload"]["text"]), 400)
        self.assertEqual(task_kwargs["summarize_payload"]["words"], 70)

    @patch("switchboard.api.views.celery_app.send_task")
    def test_linkedin_synopsis_uses_group_sponsor_as_tenant(self, send_task):
        permission = Permission.objects.get(codename="approve_cloud_dispatch")
        self.author.user_permissions.add(permission)
        group = Group.objects.create(
            title="Example Tenant",
            slug="example-tenant",
            description="A careful practice.",
            group_type="community",
            decorators=[],
            additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.author.id,
        )
        self.piece.set_sponsor(group)
        self.piece.save(update_fields=["sponsor_content_type", "sponsor_object_id", "updated_at"])

        response = self.client.post(
            "/api/switchboard/agent/synopsis/linkedin",
            {"piece_id": str(self.piece.id), "surface": "writing"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        action_run = ActionRun.objects.get(pk=response.json()["action_run_id"])
        self.assertEqual(action_run.tenant_id, group.id)
        self.assertEqual(action_run.tenant_namespace, "group:example-tenant")
        task_kwargs = send_task.call_args.kwargs["kwargs"]
        self.assertEqual(task_kwargs["tenant_id"], str(group.id))
        self.assertEqual(task_kwargs["tenant_namespace"], "group:example-tenant")

    def test_editing_summary_revokes_prior_confirmation(self):
        synopsis, _ = WritingSynopsis.objects.get_or_create(piece=self.piece)
        synopsis.description = "Previously confirmed."
        synopsis.public_synopsis_confirmed = True
        synopsis.save(
            update_fields=["description", "public_synopsis_confirmed", "updated_at"]
        )

        response = self.client.patch(
            f"/api/atelier/{self.piece.slug}/summaries/",
            {"public_synopsis": "An edited public preview."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        synopsis.refresh_from_db()
        self.assertEqual(synopsis.description, "An edited public preview.")
        self.assertFalse(synopsis.public_synopsis_confirmed)
