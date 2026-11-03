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


class ActionRunOutcomeTests(TestCase):
    """SW-11.11: acceptance vs. rejection per tool, set by the initiating person."""

    def setUp(self):
        self.user = User.objects.create_user(username="outcome-user", password="testpass123")
        self.other = User.objects.create_user(username="outcome-other", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.action_run = ActionRun.objects.create(
            tool_name="stackroom.retrieve",
            status=ActionRunStatus.SUCCEEDED,
            execution_mode=ActionRunExecutionMode.LOCAL,
            tenant_id=_TENANT_ID,
            tenant_namespace=_TENANT_NAMESPACE,
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(self.user.pk),
        )

    def test_accepts_a_valid_outcome(self):
        response = self.client.post(
            f"/api/initiatives/action-runs/{self.action_run.id}/outcome",
            {"outcome": "accepted"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "accepted")
        self.action_run.refresh_from_db()
        self.assertEqual(self.action_run.outcome, "accepted")

    def test_rejects_an_invalid_outcome_value(self):
        response = self.client.post(
            f"/api/initiatives/action-runs/{self.action_run.id}/outcome",
            {"outcome": "not-a-real-outcome"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_only_the_initiating_person_can_set_it(self):
        other_client = APIClient()
        other_client.force_authenticate(self.other)

        response = other_client.post(
            f"/api/initiatives/action-runs/{self.action_run.id}/outcome",
            {"outcome": "accepted"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.action_run.refresh_from_db()
        self.assertIsNone(self.action_run.outcome)
