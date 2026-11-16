"""Folio Dictionary commands: add, edit, remove, merge refused, receipts, API,
and Confirm and remember on the checked-finding decision path."""
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from folio.dictionary import budget
from folio.dictionary.commands import (add_entry, edit_entry, merge_entries, open_dictionary, read_dictionary,
                                       read_entry, remove_entry)
from folio.dictionary.provider import provide
from folio.models import (Folio, FolioDictionaryEntry, FolioDictionaryEntryRevision, FolioDictionaryOperation,
                          FolioInterpretation, FolioNote, FolioSightingDecision)
from folio.services.interpretation import current_context, decide_sighting, prepare_context
from heddle.bundle import digest
from heddle.errors import InterpretationError
from initiatives.models import ActionRun
from storyboard.models import Entity


class DictionaryCase(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.user = users.create_user(username="dictionary-writer")
        self.other = users.create_user(username="dictionary-other")
        self.folio = Folio.objects.create(title="Quiet City", work_type="fiction", sponsor=self.user,
                                          author=self.user, submitted_by=self.user)

    def open(self):
        open_dictionary(author=self.user, folio_id=self.folio.pk)
        self.folio.refresh_from_db()

    def revision(self):
        self.folio.refresh_from_db()
        return self.folio.dictionary_revision

    def add(self, main="Mara", *variants, **overrides):
        args = dict(author=self.user, folio_id=self.folio.pk, operation_id=uuid4(),
                    expected_dictionary_revision=self.revision(), shape_id="writing.character",
                    main_name=main, variants=list(variants), note="", new_entity_name=main)
        args.update(overrides)
        return add_entry(**args)

    def edit(self, entry, **overrides):
        args = dict(author=self.user, folio_id=self.folio.pk, entry_id=entry["entry_id"], operation_id=uuid4(),
                    expected_dictionary_revision=self.revision(), expected_entry_revision=entry["revision"])
        args.update(overrides)
        return edit_entry(**args)

    def refused(self, code, call, *args, **kwargs):
        with self.assertRaises(InterpretationError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception


class DictionaryCommandTests(DictionaryCase):
    def test_writes_need_an_opened_dictionary(self):
        self.refused("dictionary_not_open", self.add, expected_dictionary_revision=0)
        self.assertEqual(FolioDictionaryEntry.objects.count(), 0)
        self.assertEqual(Entity.objects.count(), 0)

    def test_add_writes_entry_revision_and_receipt_and_advances_both_revisions(self):
        self.open()
        before = self.folio.context_revision
        result = self.add("Mara", "Mar", note="the lighthouse keeper's daughter")
        self.folio.refresh_from_db()
        self.assertEqual((self.folio.dictionary_revision, self.folio.context_revision), (1, before + 1))
        self.assertFalse(result["replayed"])
        entry = FolioDictionaryEntry.objects.get()
        self.assertEqual((entry.main_name, entry.variants, entry.shape_version), ("Mara", ["Mar"], "0.2.0"))
        self.assertEqual(entry.entity.kind, "character")
        revision = FolioDictionaryEntryRevision.objects.get()
        self.assertEqual((revision.revision, revision.operation, revision.dictionary_revision), (1, "add", 1))
        self.assertEqual(revision.value["provenance"]["kind"], "person")
        self.assertEqual(revision.value["note"], "the lighthouse keeper's daughter")
        self.assertEqual(set(revision.value) - {"note"},
                         {"entry_id", "revision", "shape_id", "shape_version", "names", "provenance"})
        self.assertEqual(FolioDictionaryOperation.objects.get().kind, "add")
        served = provide(self.user, self.folio)
        self.assertEqual(served["revision"], 1)
        self.assertEqual(served["entries"][0]["names"], {"main": "Mara", "variants": ["Mar"]})
        self.assertNotIn("lighthouse", str(served))

    def test_same_operation_replays_and_a_changed_request_is_refused(self):
        self.open()
        operation = uuid4()
        first = self.add(operation_id=operation, expected_dictionary_revision=0)
        again = self.add(operation_id=operation, expected_dictionary_revision=0)
        self.assertTrue(again["replayed"])
        self.assertEqual({k: v for k, v in again.items() if k != "replayed"},
                         {k: v for k, v in first.items() if k != "replayed"})
        self.assertEqual((FolioDictionaryEntry.objects.count(), self.revision()), (1, 1))
        self.refused("request_conflict", self.add, "Lucy", operation_id=operation, expected_dictionary_revision=0)

    def test_stale_dictionary_revision_is_refused(self):
        self.open()
        self.add()
        self.refused("dictionary_conflict", self.add, "Lucy", expected_dictionary_revision=0)
        self.assertEqual(FolioDictionaryEntry.objects.count(), 1)

    def test_only_the_folios_shapes_are_allowed(self):
        self.open()
        self.refused("unsupported_shape", self.add, shape_id="writing.scene")
        self.folio.work_type = ""
        self.folio.save()
        self.refused("unsupported_shape", self.add)
        self.folio.work_type = "fiction"
        self.folio.save()
        setting = self.add("Harbour", shape_id="writing.setting")
        self.assertEqual(Entity.objects.get(pk=setting["entry"]["entity_id"]).kind, "setting")

    def test_entity_must_be_this_sponsors_and_of_the_shapes_kind(self):
        self.open()
        theirs = Entity.objects.create(kind="character", name="Mara", sponsor=self.other, created_by=self.other)
        place = Entity.objects.create(kind="setting", name="Harbour", sponsor=self.user, created_by=self.user)
        self.refused("not_found", self.add, entity_id=theirs.pk, new_entity_name=None)
        self.refused("not_found", self.add, entity_id=place.pk, new_entity_name=None)
        self.refused("invalid_target", self.add, entity_id=place.pk)
        self.refused("invalid_target", self.add, new_entity_name=None)
        self.assertEqual(theirs.name, Entity.objects.get(pk=theirs.pk).name)

    def test_one_active_entry_per_entity_and_shape(self):
        self.open()
        first = self.add()
        self.refused("entry_exists", self.add, entity_id=first["entry"]["entity_id"], new_entity_name=None)

    def test_names_and_note_follow_contours_limits(self):
        self.open()
        for main, variants, code in [("", [], "invalid_name"), ("   ", [], "invalid_name"),
                                     ("M" * 256, [], "invalid_name"), ("Mara", [" "], "invalid_variants"),
                                     ("Mara", ["Mar", "Mar"], "invalid_variants"),
                                     ("Mara", [f"v{i}" for i in range(33)], "invalid_variants")]:
            self.refused(code, self.add, main, *variants)
        self.refused("invalid_note", self.add, note="n" * 2001)
        self.assertEqual((FolioDictionaryEntry.objects.count(), Entity.objects.count(), self.revision()), (0, 0, 0))
        stored = self.add(" Mara  ", "ＭＡＲＡ")  # stored exactly as typed
        self.assertEqual(stored["entry"]["names"], {"main": " Mara  ", "variants": ["ＭＡＲＡ"]})

    def test_an_add_past_the_budget_is_refused_and_writes_nothing(self):
        self.open()
        long = "x" * 255
        for i in range(4):
            self.add(f"{i}{long[1:]}", *[f"{i}{j:02d}{long[3:]}" for j in range(32)])
        error = self.refused("dictionary_full", self.add, "One more", *[f"{j:02d}{long[2:]}" for j in range(32)])
        self.assertEqual(error.status, 413)
        self.assertEqual((FolioDictionaryEntry.objects.count(), self.revision()), (4, 4))
        self.assertLessEqual(budget.projected_snapshot_size(4, provide(self.user, self.folio)["entries"]),
                             budget.SNAPSHOT_BUDGET)

    def test_edit_keeps_the_earlier_revision_resolvable(self):
        self.open()
        entry = self.add("Mara", "Mar")["entry"]
        edited = self.edit(entry, main_name="Mara Vell", variants=["Mara"], note="renamed in draft two")
        self.assertEqual((edited["entry"]["revision"], edited["dictionary_revision"]), (2, 2))
        first, second = FolioDictionaryEntryRevision.objects.filter(entry_id=entry["entry_id"]).order_by("revision")
        self.assertEqual(first.value["names"], {"main": "Mara", "variants": ["Mar"]})
        self.assertEqual(second.value["names"], {"main": "Mara Vell", "variants": ["Mara"]})
        self.assertEqual(provide(self.user, self.folio)["entries"][0]["revision"], 2)

    def test_edit_refuses_stale_unchanged_and_over_budget(self):
        self.open()
        entry = self.add()["entry"]
        self.refused("entry_conflict", self.edit, entry, main_name="Mara Vell", expected_entry_revision=2)
        self.refused("no_change", self.edit, entry, main_name="Mara")
        self.refused("invalid_variants", self.edit, entry, variants=["a", "a"])
        long = "x" * 255
        for i in range(4):
            self.add(f"{i}{long[1:]}", *[f"{i}{j:02d}{long[3:]}" for j in range(32)])
        self.refused("dictionary_full", self.edit, entry, variants=[f"{j:02d}{long[2:]}" for j in range(32)])
        self.assertEqual(FolioDictionaryEntry.objects.get(pk=entry["entry_id"]).revision, 1)

    def test_remove_stops_matching_and_keeps_history_and_entity(self):
        self.open()
        entry = self.add()["entry"]
        removed = remove_entry(author=self.user, folio_id=self.folio.pk, entry_id=entry["entry_id"],
                               operation_id=uuid4(), expected_dictionary_revision=1, expected_entry_revision=1)
        self.assertEqual((removed["entry"]["state"], removed["dictionary_revision"]), ("removed", 2))
        self.assertEqual(provide(self.user, self.folio)["entries"], [])
        self.assertEqual(read_dictionary(author=self.user, folio_id=self.folio.pk)["entries"], [])
        self.assertEqual([r["operation"] for r in read_entry(author=self.user, folio_id=self.folio.pk,
                                                             entry_id=entry["entry_id"])["revisions"]], ["add", "remove"])
        self.assertTrue(Entity.objects.filter(pk=entry["entity_id"]).exists())
        self.refused("entry_not_active", self.edit, {**entry, "revision": 2}, main_name="Mara Vell")
        again = self.add(entity_id=entry["entity_id"], new_entity_name=None)  # may be added back
        self.assertNotEqual(again["entry"]["entry_id"], entry["entry_id"])

    def test_merge_is_refused_for_now(self):
        self.open()
        self.refused("merge_not_supported", merge_entries, author=self.user, folio_id=self.folio.pk)

    def test_strangers_see_nothing_and_change_nothing(self):
        self.open()
        entry = self.add()["entry"]
        self.refused("not_found", read_dictionary, author=self.other, folio_id=self.folio.pk)
        self.refused("not_found", read_entry, author=self.other, folio_id=self.folio.pk, entry_id=entry["entry_id"])
        self.refused("not_found", self.add, "Lucy", author=self.other)
        self.refused("not_found", self.edit, entry, author=self.other, main_name="Lucy")
        theirs = Folio.objects.create(title="Elsewhere", work_type="fiction", sponsor=self.other,
                                      author=self.other, submitted_by=self.other)
        self.refused("not_found", read_entry, author=self.other, folio_id=theirs.pk, entry_id=entry["entry_id"])
        self.assertEqual(FolioDictionaryEntry.objects.get().main_name, "Mara")

    def test_receipts_are_write_once(self):
        self.open()
        self.add()
        receipt = FolioDictionaryOperation.objects.get()
        with self.assertRaises(ValueError):
            receipt.save()
        with self.assertRaises(ValueError):
            receipt.delete()


class DictionaryApiTests(DictionaryCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.base = f"/api/folio/folios/{self.folio.pk}/dictionary"

    def test_add_read_edit_remove_merge(self):
        self.assertEqual(self.client.get(self.base).json()["dictionary_revision"], None)
        self.open()
        body = {"operation_id": str(uuid4()), "expected_dictionary_revision": 0, "shape_id": "writing.character",
                "main_name": "Mara", "variants": ["Mar"], "new_entity_name": "Mara"}
        added = self.client.post(self.base, body, format="json")
        self.assertEqual(added.status_code, 200, added.content)
        entry = added.json()["entry"]
        self.assertTrue(self.client.post(self.base, body, format="json").json()["replayed"])
        listed = self.client.get(self.base).json()
        self.assertEqual((listed["dictionary_revision"], len(listed["entries"])), (1, 1))
        url = f"{self.base}/{entry['entry_id']}"
        patched = self.client.patch(url, {"operation_id": str(uuid4()), "expected_dictionary_revision": 1,
                                          "expected_entry_revision": 1, "note": "keeper"}, format="json")
        self.assertEqual(patched.json()["entry"]["note"], "keeper")
        self.assertEqual(len(self.client.get(url).json()["revisions"]), 2)
        stale = self.client.patch(url, {"operation_id": str(uuid4()), "expected_dictionary_revision": 1,
                                        "expected_entry_revision": 2, "note": "x"}, format="json")
        self.assertEqual((stale.status_code, stale.json()["error"]), (409, "dictionary_conflict"))
        merge = self.client.post(f"{url}/merge", {}, format="json")
        self.assertEqual((merge.status_code, merge.json()["error"]), (422, "merge_not_supported"))
        removed = self.client.post(f"{url}/remove", {"operation_id": str(uuid4()), "expected_dictionary_revision": 2,
                                                     "expected_entry_revision": 2}, format="json")
        self.assertEqual(removed.json()["entry"]["state"], "removed")

    def test_full_dictionary_says_so_plainly(self):
        self.open()
        long = "x" * 255
        for i in range(4):
            self.add(f"{i}{long[1:]}", *[f"{i}{j:02d}{long[3:]}" for j in range(32)])
        response = self.client.post(self.base, {"operation_id": str(uuid4()), "expected_dictionary_revision": 4,
            "shape_id": "writing.character", "main_name": "One more",
            "variants": [f"{j:02d}{long[2:]}" for j in range(32)], "new_entity_name": "One more"}, format="json")
        self.assertEqual((response.status_code, response.json()["error"]), (413, "dictionary_full"))
        self.assertIn("Dictionary is full", response.json()["message"])

    def test_strangers_get_404(self):
        self.open()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.assertEqual(self.client.post(self.base, {}, format="json").status_code, 404)


class ConfirmAndRememberTests(DictionaryCase):
    """`decide_sighting(..., remember=True)`: the decision and the entry, one transaction."""

    def setUp(self):
        super().setUp()
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user, source_type="text",
                                             raw_text="Mara returns.")
        self.context = prepare_context(author=self.user, folio_id=self.folio.pk, expected_revision=0)
        self.attempt = uuid4()
        self.sighting = {"sighting_id": "c1", "shape_id": "writing.character", "shape_version": "0.1.0",
            "name_as_said": "Mara", "confidence": "medium", "uncertain": [],
            "source_locator": [{"source_ref": "note:1", "source_revision": 0, "start": 0, "end": 4, "quote": "Mara"}]}
        second = deepcopy(self.sighting)
        second.update(sighting_id="c2", source_locator=[{**self.sighting["source_locator"][0], "quote": "Mar"}])
        state = {"attempt_id": str(self.attempt), "status": "succeeded", "revision": 0, "context": self.context,
                 "steps": [], "sources": [{"source_ref": "note:1", "source_revision": 0, "text": self.note.text}],
                 "findings": {"sightings": [self.sighting, second]}, "history": []}
        self.parent = ActionRun.objects.create(tool_name="folio.reading", status="pending", initiator_type="human",
            initiator_id=str(self.user.pk), tenant_id="00000000-0000-0000-0000-000000000001",
            tenant_namespace="platform:crossroads", request_payload={"interpretation": state})
        self.reading = FolioInterpretation.objects.create(folio_note=self.note, initiated_by=self.user,
                                                          action_run=self.parent)

    def decide(self, **overrides):
        self.folio.refresh_from_db()
        args = dict(author=self.user, interpretation_id=self.reading.pk, attempt_id=self.attempt, sighting_id="c1",
                    request_id=uuid4(), disposition="link_entity", new_entity_name="Mara Vell", remember=True,
                    reviewed_digest=digest(current_context(self.folio)), reaffirmed=True)
        args.update(overrides)
        return decide_sighting(**args)

    def test_confirm_and_remember_writes_decision_entity_and_entry_together(self):
        self.open()
        decision = self.decide()
        entry = decision.dictionary_entry
        self.assertEqual((entry.main_name, entry.variants, entry.shape_version), ("Mara Vell", ["Mara"], "0.2.0"))
        self.assertEqual(entry.entity_id, decision.entity_id)
        self.assertEqual(FolioDictionaryOperation.objects.get().kind, "remember")
        self.assertEqual(self.revision(), 1)
        self.assertEqual(provide(self.user, self.folio)["entries"][0]["entry_id"], str(entry.pk))

    def test_replay_writes_nothing_twice(self):
        self.open()
        self.folio.refresh_from_db()
        args = dict(author=self.user, interpretation_id=self.reading.pk, attempt_id=self.attempt, sighting_id="c1",
                    request_id=uuid4(), disposition="link_entity", new_entity_name="Mara Vell", remember=True,
                    reviewed_digest=digest(current_context(self.folio)), reaffirmed=True)
        first = decide_sighting(**args)
        again = decide_sighting(**args)  # the context has moved on; a replay still returns the receipt
        self.assertEqual(first.pk, again.pk)
        self.assertEqual((FolioDictionaryEntry.objects.count(), FolioDictionaryOperation.objects.count(),
                          Entity.objects.count(), self.revision()), (1, 1, 1, 1))

    def test_a_second_spelling_is_added_to_the_same_entry(self):
        self.open()
        first = self.decide()
        second = self.decide(sighting_id="c2", entity_id=first.entity_id, new_entity_name=None)
        entry = FolioDictionaryEntry.objects.get()
        self.assertEqual(second.dictionary_entry_id, entry.pk)
        self.assertEqual((entry.variants, entry.revision, self.revision()), (["Mara", "Mar"], 2, 2))

    def test_an_already_known_spelling_changes_nothing(self):
        self.open()
        first = self.decide(new_entity_name="Mara")
        self.assertEqual(first.dictionary_entry.variants, [])
        receipts = FolioDictionaryOperation.objects.count()
        self.decide(sighting_id="c2", entity_id=first.entity_id, new_entity_name=None)
        entry = FolioDictionaryEntry.objects.get()
        self.assertEqual((entry.variants, entry.revision), (["Mar"], 2))
        self.assertEqual(FolioDictionaryOperation.objects.count(), receipts + 1)

    def test_without_an_opened_dictionary_nothing_is_written(self):
        with self.assertRaises(InterpretationError) as caught:
            self.decide()
        self.assertEqual(caught.exception.code, "dictionary_not_open")
        self.assertEqual((FolioSightingDecision.objects.count(), Entity.objects.count(),
                          FolioDictionaryEntry.objects.count()), (0, 0, 0))

    def test_a_full_dictionary_rolls_the_decision_back(self):
        self.open()
        self.add("Lucy")
        tight = budget.projected_snapshot_size(2, provide(self.user, self.folio)["entries"])
        with patch("folio.dictionary.budget.SNAPSHOT_BUDGET", tight), self.assertRaises(InterpretationError) as caught:
            self.decide(new_entity_name="M" * 255)
        self.assertEqual(caught.exception.code, "dictionary_full")
        self.assertEqual(FolioSightingDecision.objects.count(), 0)
        self.assertFalse(Entity.objects.filter(name="M" * 255).exists())

    def test_remember_only_goes_with_a_link(self):
        self.open()
        for disposition in ("dismiss", "defer"):
            with self.assertRaises(InterpretationError) as caught:
                self.decide(disposition=disposition, new_entity_name=None)
            self.assertEqual(caught.exception.code, "invalid_remember")
        with self.assertRaises(InterpretationError):
            self.decide(remember="yes")
        self.assertEqual(FolioSightingDecision.objects.count(), 0)

    def test_a_plain_link_still_leaves_the_dictionary_alone(self):
        self.open()
        decision = self.decide(remember=False)
        self.assertIsNone(decision.dictionary_entry)
        self.assertEqual((FolioDictionaryEntry.objects.count(), self.revision()), (0, 0))
