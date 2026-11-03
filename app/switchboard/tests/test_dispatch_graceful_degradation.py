from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from initiatives.models import (
    ActionRun,
    ActionRunExecutionMode,
    ActionRunInitiatorType,
    ActionRunStatus,
)
from switchboard.dispatch import enqueue_switchboard_task
from switchboard.tasks import sweep_stale_action_runs

User = get_user_model()

_TENANT_ID = "00000000-0000-0000-0000-000000000001"
_TENANT_NAMESPACE = "platform:crossroads"


def _make_action_run(**overrides):
    defaults = dict(
        tool_name="console.classify",
        status=ActionRunStatus.PENDING,
        execution_mode=ActionRunExecutionMode.LOCAL,
        service_name="switchboard",
        tenant_id=_TENANT_ID,
        tenant_namespace=_TENANT_NAMESPACE,
        initiator_type=ActionRunInitiatorType.HUMAN,
        initiator_id="1",
    )
    defaults.update(overrides)
    return ActionRun.objects.create(**defaults)


class EnqueueSwitchboardTaskTests(TestCase):
    """SW-11.12, failure mode (a): the broker itself is unreachable at send_task time."""

    @patch("mixtape.celery_app.app.send_task")
    def test_broker_failure_marks_action_run_failed_and_returns_false(self, send_task):
        send_task.side_effect = ConnectionRefusedError("[Errno 61] Connection refused")
        action_run = _make_action_run()

        result = enqueue_switchboard_task(
            "switchboard.classify_async",
            kwargs={"action_run_id": str(action_run.id)},
            action_run=action_run,
        )

        self.assertFalse(result)
        action_run.refresh_from_db()
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(action_run.error_payload["error"], "switchboard_unavailable")
        self.assertIsNotNone(action_run.completed_at)

    @patch("mixtape.celery_app.app.send_task")
    def test_successful_dispatch_leaves_action_run_untouched(self, send_task):
        action_run = _make_action_run()

        result = enqueue_switchboard_task(
            "switchboard.classify_async",
            kwargs={"action_run_id": str(action_run.id)},
            action_run=action_run,
        )

        self.assertTrue(result)
        send_task.assert_called_once()
        action_run.refresh_from_db()
        self.assertEqual(action_run.status, ActionRunStatus.PENDING)


class ProxyViewBrokerFailureTests(TestCase):
    """A broker failure at an actual proxy view returns 503, not an unhandled 500."""

    def setUp(self):
        self.user = User.objects.create_user(username="broker-failure-user", password="testpass123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("mixtape.celery_app.app.send_task")
    def test_classify_async_proxy_returns_503_on_broker_failure(self, send_task):
        send_task.side_effect = ConnectionRefusedError("[Errno 61] Connection refused")

        response = self.client.post(
            "/api/switchboard/classify/async",
            {"text": "x" * 40, "max_tags": 5},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertIn("action_run_id", data)
        action_run = ActionRun.objects.get(pk=data["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(action_run.error_payload["error"], "switchboard_unavailable")


class SweepStaleActionRunsTests(TestCase):
    """SW-11.12, failure mode (b): the broker is fine but Switchboard's worker
    never advances the ActionRun past PENDING/RUNNING."""

    def test_sweeps_stale_pending_and_running_runs(self):
        stale_pending = _make_action_run(
            started_at=timezone.now() - timedelta(minutes=30),
        )
        stale_running = _make_action_run(
            status=ActionRunStatus.RUNNING,
            started_at=timezone.now() - timedelta(minutes=30),
        )
        fresh = _make_action_run(started_at=timezone.now())
        non_switchboard = _make_action_run(
            service_name="other",
            started_at=timezone.now() - timedelta(minutes=30),
        )

        result = sweep_stale_action_runs()

        self.assertEqual(result["swept"], 2)
        for run in (stale_pending, stale_running):
            run.refresh_from_db()
            self.assertEqual(run.status, ActionRunStatus.FAILED)
            self.assertEqual(run.error_payload["error"], "switchboard_unavailable")

        fresh.refresh_from_db()
        self.assertEqual(fresh.status, ActionRunStatus.PENDING)

        non_switchboard.refresh_from_db()
        self.assertEqual(non_switchboard.status, ActionRunStatus.PENDING)

    def test_succeeded_runs_are_never_swept(self):
        succeeded = _make_action_run(
            status=ActionRunStatus.SUCCEEDED,
            started_at=timezone.now() - timedelta(minutes=30),
        )

        sweep_stale_action_runs()

        succeeded.refresh_from_db()
        self.assertEqual(succeeded.status, ActionRunStatus.SUCCEEDED)
