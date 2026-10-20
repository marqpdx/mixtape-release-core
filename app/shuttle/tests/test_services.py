import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from initiatives.models import ActionRun, ActionRunStatus
from shuttle.services import ShuttleEnvelopeError, get_held_packet, hold_packet, start_weave

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contract" / "fixtures"


def load_json(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class StartWeaveTests(TestCase):
    """SH-7b (a): the envelope's ActionRun, created before any packet exists."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.weave_in = load_json("three_choirs_weave_in.json")

    def test_start_weave_creates_a_pending_action_run(self):
        action_run = start_weave(weave_in=self.weave_in, author=self.author)
        self.assertEqual(action_run.status, ActionRunStatus.PENDING)
        self.assertEqual(action_run.tool_name, "shuttle.weave")
        self.assertEqual(action_run.service_name, "shuttle")
        self.assertEqual(action_run.initiator_id, str(self.author.pk))
        self.assertEqual(action_run.request_payload, {"weave_in": self.weave_in})

    def test_each_call_is_a_separate_weave(self):
        run_a = start_weave(weave_in=self.weave_in, author=self.author)
        run_b = start_weave(weave_in=self.weave_in, author=self.author)
        self.assertNotEqual(run_a.id, run_b.id)


class HoldPacketTests(TestCase):
    """SH-7b (a): attaching a built packet to an already-started weave."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.other_author = get_user_model().objects.create_user(
            username="someone-else", email="someone-else@example.com", password="x"
        )
        self.weave_in = load_json("three_choirs_weave_in.json")
        # action_run_id is server-assigned; the fixture's is a placeholder.
        self.packet = {**load_json("three_choirs_packet_out.json")}
        del self.packet["action_run_id"]

    def _start(self, author=None):
        return start_weave(weave_in=self.weave_in, author=author or self.author)

    def test_hold_packet_attaches_to_the_existing_action_run(self):
        action_run = self._start()
        held = hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        self.assertEqual(held["action_run_id"], str(action_run.id))

    def test_hold_packet_does_not_create_a_second_action_run(self):
        action_run = self._start()
        before = ActionRun.objects.count()
        hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        self.assertEqual(ActionRun.objects.count(), before)

    def test_hold_packet_returns_a_schema_valid_packet(self):
        action_run = self._start()
        held = hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        self.assertEqual(held["version"], "1.0")
        self.assertEqual(len(held["items"]), len(self.packet["items"]))

    def test_hold_packet_rejects_a_requester_who_is_not_the_initiator(self):
        action_run = self._start()
        with self.assertRaises(ShuttleEnvelopeError):
            hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.other_author)

    def test_get_held_packet_round_trips(self):
        action_run = self._start()
        held = hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        fetched = get_held_packet(action_run_id=str(action_run.id), author=self.author)
        self.assertEqual(fetched, held)

    def test_get_held_packet_rejects_a_requester_who_is_not_the_initiator(self):
        action_run = self._start()
        hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        with self.assertRaises(ShuttleEnvelopeError):
            get_held_packet(action_run_id=str(action_run.id), author=self.other_author)

    def test_get_held_packet_rejects_unknown_action_run(self):
        with self.assertRaises(ShuttleEnvelopeError):
            get_held_packet(action_run_id="00000000-0000-0000-0000-000000000099", author=self.author)

    def test_get_held_packet_rejects_non_pending_action_run(self):
        action_run = self._start()
        hold_packet(action_run_id=str(action_run.id), packet=self.packet, author=self.author)
        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.save(update_fields=["status"])

        with self.assertRaises(ShuttleEnvelopeError):
            get_held_packet(action_run_id=str(action_run.id), author=self.author)
