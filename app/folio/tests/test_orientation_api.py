from uuid import uuid4
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from folio.models import Folio, FolioNote, FolioSightingDecision
from initiatives.models import ActionRun

JACKALOPE = "this is for a fiction story, title Jackalope, locale is desert southwest, main character is Travis and second charater is Lucy, and the first scene takes place in a bar"


class FolioOrientationAPITests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="orientation-writer")
        self.other = get_user_model().objects.create_user(username="orientation-other")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.folio = Folio.objects.create(sponsor=self.user, author=self.user,
            submitted_by=self.user, title="Jackalope", work_type="fiction")
        self.base = f"/api/folio/folios/{self.folio.pk}"

    def prepare(self):
        return self.client.post(self.base + "/interpretation-context",
            {"request_id": str(uuid4()), "expected_revision": 0}, format="json")

    def test_create_explicit_fiction_and_untyped_capture(self):
        response = self.client.post("/api/folio/folios", {"title": "Jackalope", "work_type": "fiction"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["work_type"], "fiction")
        response = self.client.post("/api/folio/folios", {}, format="json")
        self.assertEqual(response.data["work_type"], "")
        invalid = self.client.post("/api/folio/folios", {"work_type": "unknown"}, format="json")
        self.assertEqual(invalid.status_code, 400)

    def test_get_context_never_writes_or_runs_model(self):
        response = self.client.get(self.base + "/interpretation-context")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["context"]["title"], "Jackalope")
        self.folio.refresh_from_db()
        self.assertEqual(self.folio.context_revision, 0)
        self.assertFalse(ActionRun.objects.exists())

    def test_prepare_replay_and_conflicting_payload(self):
        url = self.base + "/interpretation-context"
        command = {"request_id": str(uuid4()), "expected_revision": 0}
        first = self.client.post(url, command, format="json")
        replay = self.client.post(url, command, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data, replay.data)
        changed = self.client.post(url, {**command, "expected_revision": 1}, format="json")
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.data["error"], "request_conflict")

    def test_confirm_exact_values_preserves_capture_and_accepts_no_sightings(self):
        note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text=JACKALOPE)
        prepared = self.prepare()
        command = {"request_id": str(uuid4()), "expected_digest": prepared.data["context_digest"],
            "title": "Jackalope", "work_type": "fiction"}
        url = self.base + "/orientation/confirm"
        self.assertEqual(self.client.post(url, command, format="json").status_code, 200)
        self.folio.refresh_from_db()
        first_time = self.folio.orientation_confirmed_at
        self.assertEqual(self.client.post(url, command, format="json").status_code, 200)
        self.folio.refresh_from_db()
        self.assertEqual(self.folio.orientation_confirmed_at, first_time)
        note.refresh_from_db()
        self.assertEqual(note.raw_text, JACKALOPE)
        self.assertFalse(FolioSightingDecision.objects.exists())
        self.assertFalse(ActionRun.objects.exists())

    def test_confirm_different_title_conflicts(self):
        prepared = self.prepare()
        response = self.client.post(self.base + "/orientation/confirm", {
            "request_id": str(uuid4()), "expected_digest": prepared.data["context_digest"],
            "title": "Other", "work_type": "fiction"}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_title_patch_invalidates_confirmation_without_rereading_suggestion(self):
        prepared = self.prepare()
        self.client.post(self.base + "/orientation/confirm", {
            "request_id": str(uuid4()), "expected_digest": prepared.data["context_digest"],
            "title": "Jackalope", "work_type": "fiction"}, format="json")
        response = self.client.patch(self.base, {"title": "Jackalope revised"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["rereading_suggestion"])
        self.assertEqual(response.data["context_revision"], 2)
        self.assertIsNone(response.data["orientation_confirmed_at"])

    def test_type_change_requires_revision_and_suggests_only_on_change(self):
        self.assertEqual(self.client.patch(self.base, {"work_type": ""}, format="json").status_code, 400)
        response = self.client.patch(self.base, {"work_type": "", "expected_revision": 0}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["rereading_suggestion"])
        self.assertFalse(ActionRun.objects.exists())
        stale = self.client.patch(self.base, {"work_type": "fiction", "expected_revision": 0}, format="json")
        self.assertEqual(stale.status_code, 409)

    def test_other_member_context_is_hidden(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.base + "/interpretation-context").status_code, 404)
        self.assertEqual(self.prepare().status_code, 404)

    def test_commands_validate_digest_and_revision(self):
        self.assertEqual(self.client.post(self.base + "/interpretation-context", {
            "request_id": "bad", "expected_revision": -1}, format="json").status_code, 400)
        self.assertEqual(self.client.post(self.base + "/orientation/confirm", {
            "request_id": str(uuid4()), "expected_digest": "bad", "title": "Jackalope",
            "work_type": "fiction"}, format="json").status_code, 400)

    def test_confirmation_rejects_sighting_decisions(self):
        prepared = self.prepare()
        response = self.client.post(self.base + "/orientation/confirm", {
            "request_id": str(uuid4()), "expected_digest": prepared.data["context_digest"],
            "title": "Jackalope", "work_type": "fiction", "sightings": []}, format="json")
        self.assertEqual(response.status_code, 400)
        self.folio.refresh_from_db()
        self.assertIsNone(self.folio.orientation_confirmed_at)

    def test_replaying_old_confirmation_does_not_reconfirm_changed_context(self):
        prepared = self.prepare()
        command = {"request_id": str(uuid4()), "expected_digest": prepared.data["context_digest"],
            "title": "Jackalope", "work_type": "fiction"}
        url = self.base + "/orientation/confirm"
        first = self.client.post(url, command, format="json")
        self.client.patch(self.base, {"title": "New title"}, format="json")
        replay = self.client.post(url, command, format="json")
        self.assertEqual(first.data, replay.data)
        self.folio.refresh_from_db()
        self.assertIsNone(self.folio.orientation_confirmed_at)
        self.assertEqual(self.folio.title, "New title")
