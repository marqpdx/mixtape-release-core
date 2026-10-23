from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from uuid import uuid4

from initiatives.models import ActionRunStatus
from shuttle.interpretation import lifecycle
from writing.models import Seed


@override_settings(ROOT_URLCONF="shuttle.api.urls")
class KeepInNotebookApiTests(TestCase):
    """Shuttle's explicit "Keep in Notebook" exit (CTO, 2026-10-20, OQ10)."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(username="kin-weaver", email="kin@example.com", password="x")
        self.other = get_user_model().objects.create_user(username="kin-other", email="kin-other@example.com", password="x")
        self.seed = Seed.objects.create(author=self.author, body_text="a telling", kind="text", status="ready")
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.author)
        self.parent = lifecycle.begin(author=self.author, request_id=uuid4(), seed_id=self.seed.pk, client="phone")

    def test_keep_in_notebook_abandons_the_weave(self):
        resp = self.client_api.post(f"/weaves/{self.parent['weave_action_run_id']}/keep-in-notebook/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "abandoned")

    def test_abandoned_weave_still_readable_via_detail(self):
        action_run_id = self.parent["weave_action_run_id"]
        self.client_api.post(f"/weaves/{action_run_id}/keep-in-notebook/")
        resp = self.client_api.get(f"/weaves/{action_run_id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["status"], "abandoned")

    def test_abandoned_weave_rejects_correction(self):
        action_run_id = self.parent["weave_action_run_id"]
        self.client_api.post(f"/weaves/{action_run_id}/keep-in-notebook/")
        resp = self.client_api.post(f"/weaves/{action_run_id}/correct/", {
            "request_id": str(uuid4()), "expected_revision": 0, "correction_text": "a fix",
        }, format="json")
        self.assertEqual(resp.status_code, 409, resp.data)

    def test_keep_in_notebook_rejects_another_user(self):
        other_client = APIClient()
        other_client.force_authenticate(self.other)
        resp = other_client.post(f"/weaves/{self.parent['weave_action_run_id']}/keep-in-notebook/")
        self.assertEqual(resp.status_code, 404)

    def test_original_seed_is_untouched(self):
        self.client_api.post(f"/weaves/{self.parent['weave_action_run_id']}/keep-in-notebook/")
        self.seed.refresh_from_db()
        self.assertEqual(self.seed.status, "ready")
        self.assertIsNone(self.seed.promoted_to)

    def test_original_seed_is_tagged_as_shuttle_proto(self):
        """OQ12: the minimal proto-Shuttle marker on a Seed."""
        self.assertFalse(self.seed.is_shuttle_proto)
        self.client_api.post(f"/weaves/{self.parent['weave_action_run_id']}/keep-in-notebook/")
        self.seed.refresh_from_db()
        self.assertTrue(self.seed.is_shuttle_proto)

    def test_re_engaging_starts_a_fresh_weave_not_a_resume(self):
        action_run_id = self.parent["weave_action_run_id"]
        self.client_api.post(f"/weaves/{action_run_id}/keep-in-notebook/")
        fresh = lifecycle.begin(author=self.author, request_id=uuid4(), seed_id=self.seed.pk, client="phone")
        self.assertNotEqual(fresh["weave_action_run_id"], action_run_id)
