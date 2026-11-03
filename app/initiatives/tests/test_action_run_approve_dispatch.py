from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)

User = get_user_model()

_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_TENANT_NAMESPACE = "platform:crossroads"


class ActionRunApproveBrokerFailureTests(TestCase):
    """SW-11.12: approving a deferred draft/refine run that can't be
    dispatched (broker unreachable) returns 503, not an unhandled 500,
    and the ActionRun lands FAILED rather than stuck approved-but-pending."""

    def setUp(self):
        self.user = User.objects.create_user(username="approve-dispatch-user", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.action_run = ActionRun.objects.create(
            tool_name="console.draft",
            status=ActionRunStatus.PENDING,
            execution_mode=ActionRunExecutionMode.LOCAL,
            tenant_id=_TENANT_ID,
            tenant_namespace=_TENANT_NAMESPACE,
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
            request_payload={
                "content_type": "email",
                "source_text": "a draft source",
                "tone": None,
                "target_length": None,
                "audience": None,
                "additional_context": None,
                "surface": "console",
                "deferred": True,
            },
        )

    @patch("mixtape.celery_app.app.send_task")
    def test_approve_returns_503_on_broker_failure(self, send_task):
        send_task.side_effect = ConnectionRefusedError("[Errno 61] Connection refused")

        response = self.client.post(f"/api/initiatives/action-runs/{self.action_run.id}/approve")

        self.assertEqual(response.status_code, 503)
        self.action_run.refresh_from_db()
        self.assertEqual(self.action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(self.action_run.error_payload["error"], "switchboard_unavailable")

    @patch("mixtape.celery_app.app.send_task")
    def test_approve_succeeds_when_broker_is_up(self, send_task):
        response = self.client.post(f"/api/initiatives/action-runs/{self.action_run.id}/approve")

        self.assertEqual(response.status_code, 200)
        send_task.assert_called_once()
        self.action_run.refresh_from_db()
        self.assertTrue(self.action_run.cloud_approved)
