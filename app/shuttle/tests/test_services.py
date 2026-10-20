import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from initiatives.models import ActionRun, ActionRunStatus
from shuttle.services import ShuttleEnvelopeError, get_held_packet, hold_packet

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "contract" / "fixtures"


def load_json(name):
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class HoldPacketTests(TestCase):
    """SH-7b (a): the envelope's plan/preview half."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.weave_in = load_json("three_choirs_weave_in.json")
        # action_run_id is server-assigned; the fixture's is a placeholder.
        self.packet = {**load_json("three_choirs_packet_out.json")}
        del self.packet["action_run_id"]

    def test_hold_packet_creates_a_pending_action_run(self):
        held = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)

        action_run = ActionRun.objects.get(pk=held["action_run_id"])
        self.assertEqual(action_run.status, ActionRunStatus.PENDING)
        self.assertEqual(action_run.tool_name, "shuttle.weave")
        self.assertEqual(action_run.service_name, "shuttle")
        self.assertEqual(action_run.initiator_id, str(self.author.pk))

    def test_hold_packet_returns_a_schema_valid_packet(self):
        held = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)
        self.assertEqual(held["version"], "1.0")
        self.assertEqual(len(held["items"]), len(self.packet["items"]))

    def test_one_action_run_per_weave(self):
        held_a = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)
        held_b = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)
        self.assertNotEqual(held_a["action_run_id"], held_b["action_run_id"])

    def test_get_held_packet_round_trips(self):
        held = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)
        fetched = get_held_packet(action_run_id=held["action_run_id"])
        self.assertEqual(fetched, held)

    def test_get_held_packet_rejects_unknown_action_run(self):
        with self.assertRaises(ShuttleEnvelopeError):
            get_held_packet(action_run_id="00000000-0000-0000-0000-000000000099")

    def test_get_held_packet_rejects_non_pending_action_run(self):
        held = hold_packet(weave_in=self.weave_in, packet=self.packet, author=self.author)
        action_run = ActionRun.objects.get(pk=held["action_run_id"])
        action_run.status = ActionRunStatus.SUCCEEDED
        action_run.save(update_fields=["status"])

        with self.assertRaises(ShuttleEnvelopeError):
            get_held_packet(action_run_id=held["action_run_id"])
