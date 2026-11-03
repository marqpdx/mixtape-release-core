from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.test import APIClient

from initiatives.models import ActionRun, ActionRunStatus
from puddlejump.models import Library

User = get_user_model()


class RetrieveFindProxyBrokerFailureTests(TestCase):
    """SW-11.12: a broker-unreachable failure at dispatch time returns 503,
    not an unhandled 500, and the ActionRun it created is marked FAILED."""

    def setUp(self):
        self.user = User.objects.create_user(username="pj-proxy-user", password="testpass123")
        user_ct = ContentType.objects.get_for_model(self.user)
        Library.objects.create(owner_content_type=user_ct, owner_object_id=self.user.id, title="Personal")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("mixtape.celery_app.app.send_task")
    def test_retrieve_async_proxy_returns_503_on_broker_failure(self, send_task):
        send_task.side_effect = ConnectionRefusedError("[Errno 61] Connection refused")

        response = self.client.post("/api/puddlejump/retrieve/", {"query": "test query"}, format="json")

        self.assertEqual(response.status_code, 503)
        action_run = ActionRun.objects.get(pk=response.json()["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(action_run.error_payload["error"], "switchboard_unavailable")

    @patch("mixtape.celery_app.app.send_task")
    def test_find_async_proxy_returns_503_on_broker_failure(self, send_task):
        send_task.side_effect = ConnectionRefusedError("[Errno 61] Connection refused")

        response = self.client.post("/api/puddlejump/find/", {"query": "test query"}, format="json")

        self.assertEqual(response.status_code, 503)
        action_run = ActionRun.objects.get(pk=response.json()["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(action_run.error_payload["error"], "switchboard_unavailable")

    @patch("mixtape.celery_app.app.send_task")
    def test_retrieve_async_proxy_succeeds_when_broker_is_up(self, send_task):
        response = self.client.post("/api/puddlejump/retrieve/", {"query": "test query"}, format="json")

        self.assertEqual(response.status_code, 202)
        send_task.assert_called_once()
        action_run = ActionRun.objects.get(pk=response.json()["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.PENDING)
