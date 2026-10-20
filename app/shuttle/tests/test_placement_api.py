import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from shuttle.services import start_weave

FIXTURE = Path(__file__).resolve().parent.parent / "interpretation" / "spoken_choirs.findings.json"


def load_findings():
    with open(FIXTURE) as f:
        findings = json.load(f)["findings"]
    resolution = {
        s["sighting_id"]: {"status": "unresolved", "candidates": []}
        for s in findings["sightings"] if s["shape_id"] in {"shuttle.thing", "shuttle.place", "shuttle.idea"}
    }
    return {**findings, "resolution": resolution}


@override_settings(ROOT_URLCONF="shuttle.api.urls")
class BuildPacketAndConfirmApiTests(TestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user(username="api-weaver", email="aw@example.com", password="x")
        self.other = get_user_model().objects.create_user(username="api-other", email="ao@example.com", password="x")
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.author)

        self.parent = start_weave(
            weave_in={"version": "1.0", "text": "three choirs", "client": "phone", "capture_mode": "voice"},
            author=self.author,
        )
        self.parent.request_payload = {**self.parent.request_payload, "interpretation": {
            "status": "succeeded", "findings": load_findings(),
        }}
        self.parent.save(update_fields=["request_payload"])

    def test_build_packet_returns_a_packet(self):
        resp = self.client_api.post(f"/weaves/{self.parent.id}/build-packet/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["action_run_id"], str(self.parent.id))
        self.assertEqual(len(resp.data["items"]), 6)

    def test_build_packet_rejects_another_user(self):
        other_client = APIClient()
        other_client.force_authenticate(self.other)
        resp = other_client.post(f"/weaves/{self.parent.id}/build-packet/")
        self.assertEqual(resp.status_code, 404)

    def test_confirm_after_build_packet_writes_rows(self):
        built = self.client_api.post(f"/weaves/{self.parent.id}/build-packet/").data
        ticked = [i["item_id"] for i in built["items"]] + [i["idea_id"] for i in built["ideas"]] \
            + [a["adjacency_id"] for a in built["adjacencies"]]
        stories = [{"item_id": p["item_id"], "text": p["known_story"]["text"]}
                   for p in built["story_prompts"] if "known_story" in p]
        resp = self.client_api.post(f"/weaves/{self.parent.id}/confirm/", {
            "ticked_item_ids": ticked, "stories": stories,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertGreater(len(resp.data["written"]), 0)

    def test_confirm_without_build_packet_fails_cleanly(self):
        resp = self.client_api.post(f"/weaves/{self.parent.id}/confirm/", {
            "ticked_item_ids": [], "stories": [],
        }, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)
