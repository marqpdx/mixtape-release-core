from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from initiatives.models import ActionRunStatus
from shuttle.confirm import confirm_weave
from shuttle.services import ShuttleEnvelopeError, get_result, hold_packet, start_weave


@override_settings(ROOT_URLCONF="shuttle.api.urls")
class PublicationRecoveryTests(TestCase):
    """The terminal-result lookup (CTO, 2026-10-23): if Publish commits
    but the phone loses the response, it re-fetches the weave's result
    here instead of replaying confirm. Read-only, never re-invokes
    confirm_weave (ADR-0058, Heddle-adjacent, not Heddle's own concern —
    this is Shuttle's own publish, not an interpretation step)."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.other = get_user_model().objects.create_user(
            username="someone-else", email="someone-else@example.com", password="x"
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.author)

        action_run = start_weave(
            weave_in={"version": "1.0", "text": "A quick note.", "client": "phone", "capture_mode": "typed"},
            author=self.author,
        )
        self.action_run_id = str(action_run.id)
        hold_packet(action_run_id=self.action_run_id, packet={
            "anchor": {"headline": "Packet: quick note", "counts": {"places": 0, "ideas": 0, "adjacencies": 0}},
            "items": [], "ideas": [], "adjacencies": [], "story_prompts": [],
        }, author=self.author)

    def test_pending_weave_has_no_result_yet(self):
        with self.assertRaises(ShuttleEnvelopeError) as err:
            get_result(action_run_id=self.action_run_id, author=self.author)
        self.assertEqual(err.exception.status, 409)

    def test_succeeded_confirm_result_is_recoverable(self):
        confirm_weave(action_run_id=self.action_run_id, confirm_in={
            "version": "1.0", "action_run_id": self.action_run_id,
            "ticked_item_ids": [], "stories": [], "merge_answers": [],
        }, author=self.author)

        result = get_result(action_run_id=self.action_run_id, author=self.author)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["written"], [])

        response = self.client_api.get(f"/weaves/{self.action_run_id}/result/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "succeeded")

    def test_result_lookup_never_replays_confirm(self):
        """Calling it twice must not re-run confirm_weave — same result,
        no second transaction, no error about an already-closed run."""
        confirm_weave(action_run_id=self.action_run_id, confirm_in={
            "version": "1.0", "action_run_id": self.action_run_id,
            "ticked_item_ids": [], "stories": [], "merge_answers": [],
        }, author=self.author)

        first = get_result(action_run_id=self.action_run_id, author=self.author)
        second = get_result(action_run_id=self.action_run_id, author=self.author)
        self.assertEqual(first, second)

    def test_someone_elses_weave_reads_as_not_found(self):
        response = self.client_api.get(f"/weaves/{self.action_run_id}/result/")
        self.client_api.force_authenticate(self.other)
        response = self.client_api.get(f"/weaves/{self.action_run_id}/result/")
        self.assertEqual(response.status_code, 404)

    def test_unknown_action_run_is_not_found(self):
        response = self.client_api.get("/weaves/00000000-0000-0000-0000-000000000000/result/")
        self.assertEqual(response.status_code, 404)
