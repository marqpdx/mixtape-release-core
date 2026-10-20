import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from classifications.models import Tag
from commons.services import capture_item
from initiatives.models import ActionRun, ActionRunStatus
from shuttle import placement
from shuttle.contract.validate import validate_packet_out
from shuttle.services import start_weave
from tapestry.models import Location, Place

FIXTURE = Path(__file__).resolve().parent.parent / "interpretation" / "spoken_choirs.findings.json"


def load_findings():
    with open(FIXTURE) as f:
        return json.load(f)["findings"]


def with_unresolved_resolution(findings):
    resolution = {
        s["sighting_id"]: {"status": "unresolved", "candidates": []}
        for s in findings["sightings"] if s["shape_id"] in {"shuttle.thing", "shuttle.place", "shuttle.idea"}
    }
    return {**findings, "resolution": resolution}


class ResolveSightingsTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user(username="w", email="w@example.com", password="x")
        self.findings = with_unresolved_resolution(load_findings())

    def test_found_thing_resolves_to_existing_row(self):
        existing = capture_item(self.author, title="Choir! Choir! Choir!")
        resolved = placement.resolve_sightings(self.findings)
        entry = resolved["resolution"]["thing-toronto"]
        self.assertEqual(entry["status"], "found")
        self.assertEqual(entry["candidates"][0]["id"], str(existing.id))

    def test_new_thing_resolves_to_new(self):
        resolved = placement.resolve_sightings(self.findings)
        entry = resolved["resolution"]["thing-australia"]
        self.assertEqual(entry["status"], "new")
        self.assertEqual(entry["candidates"], [])

    def test_found_place_resolves_to_existing_row(self):
        existing = Place.objects.create(name="Toronto", location=Location.objects.create())
        resolved = placement.resolve_sightings(self.findings)
        entry = resolved["resolution"]["locale-toronto"]
        self.assertEqual(entry["status"], "found")
        self.assertEqual(entry["candidates"][0]["id"], str(existing.id))

    def test_near_duplicate_idea_surfaces_a_candidate(self):
        Tag.objects.create(title="Singing Together!", slug="singing-together-bang", is_idea=True)
        resolved = placement.resolve_sightings(self.findings)
        entry = resolved["resolution"]["idea-singing"]
        self.assertIn(entry["status"], {"found", "near_duplicate"})
        self.assertTrue(entry["candidates"])

    def test_already_resolved_entries_are_left_alone(self):
        findings = {**self.findings, "resolution": {
            **self.findings["resolution"],
            "thing-toronto": {"status": "found", "candidates": [{"id": "x", "name": "x", "score": 1.0}]},
        }}
        resolved = placement.resolve_sightings(findings)
        self.assertEqual(resolved["resolution"]["thing-toronto"]["candidates"][0]["id"], "x")


class AssemblePacketTests(TestCase):
    def setUp(self):
        self.findings = placement.resolve_sightings(with_unresolved_resolution(load_findings()))
        self.packet = placement.assemble_packet(self.findings)

    def test_packet_validates_against_the_sh7a_schema(self):
        validate_packet_out({**self.packet, "version": "1.0", "action_run_id": "test"})

    def test_three_places_and_three_things_become_six_items(self):
        self.assertEqual(len(self.packet["items"]), 6)
        kinds = {i["kind"] for i in self.packet["items"]}
        self.assertEqual(kinds, {"place", "thing"})

    def test_thing_locale_comes_from_its_place(self):
        thing = next(i for i in self.packet["items"] if i["item_id"] == "thing-toronto")
        self.assertEqual(thing["locale"], "Toronto")

    def test_one_idea_one_adjacency_cluster_of_three(self):
        self.assertEqual(len(self.packet["ideas"]), 1)
        self.assertEqual(len(self.packet["adjacencies"]), 3)

    def test_story_on_a_thing_subject_attaches_to_its_place_item(self):
        prompt = next(p for p in self.packet["story_prompts"] if p["item_id"] == "locale-toronto")
        self.assertIn("known_story", prompt)
        self.assertTrue(prompt["known_story"]["text"].startswith("it's a great experience"))

    def test_places_without_a_story_get_a_bare_prompt(self):
        prompt = next(p for p in self.packet["story_prompts"] if p["item_id"] == "locale-australia")
        self.assertNotIn("known_story", prompt)

    def test_stories_not_yet_told_is_always_omitted(self):
        self.assertNotIn("stories_not_yet_told", self.packet)


class BuildPacketTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user(username="w2", email="w2@example.com", password="x")
        self.parent = start_weave(
            weave_in={"version": "1.0", "text": "three choirs", "client": "phone", "capture_mode": "voice"},
            author=self.author,
        )
        self.parent.request_payload = {**self.parent.request_payload, "interpretation": {
            "status": "succeeded", "findings": with_unresolved_resolution(load_findings()),
        }}
        self.parent.save(update_fields=["request_payload"])

    def test_build_packet_holds_a_valid_packet(self):
        held = placement.build_packet(action_run_id=str(self.parent.id), author=self.author)
        self.assertEqual(held["action_run_id"], str(self.parent.id))
        self.assertEqual(len(held["items"]), 6)

    def test_build_packet_requires_succeeded_interpretation(self):
        self.parent.request_payload["interpretation"]["status"] = "pending"
        self.parent.save(update_fields=["request_payload"])
        with self.assertRaises(placement.PlacementError):
            placement.build_packet(action_run_id=str(self.parent.id), author=self.author)

    def test_build_packet_persists_resolution_back_onto_the_parent(self):
        placement.build_packet(action_run_id=str(self.parent.id), author=self.author)
        self.parent.refresh_from_db()
        resolution = self.parent.request_payload["interpretation"]["findings"]["resolution"]
        self.assertEqual(resolution["thing-australia"]["status"], "new")

    def test_build_packet_rejects_a_requester_who_is_not_the_initiator(self):
        other = get_user_model().objects.create_user(username="other2", email="other2@example.com", password="x")
        with self.assertRaises(Exception):
            placement.build_packet(action_run_id=str(self.parent.id), author=other)
