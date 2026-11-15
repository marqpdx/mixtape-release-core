"""Dictionary storage, the slim snapshot, opening, and the size guard."""
from io import StringIO
from types import SimpleNamespace
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch

from folio.dictionary import budget, provider
from folio.dictionary.commands import open_dictionary
from folio.interpretation import recognition as rec
from folio.interpretation import recognition_contract as wire
from folio.interpretation.lifecycle import begin_reading
from folio.models import Folio, FolioDictionaryEntry, FolioDictionaryEntryRevision, FolioNote
from heddle import lifecycle
from heddle.errors import InterpretationError
from initiatives.models import ActionRun
from storyboard.models import Entity

CAP = wire.PROFILE["max_context_chars"]


def size(value):
    return len(wire.canonical(value).decode("utf-8"))


@override_settings(FOLIO_RECOGNITION_ENABLED=True)
class DictionaryStorageTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.user = users.create_user(username="storage-writer")
        self.other = users.create_user(username="storage-other")
        self.folio = self.make_folio(self.user)
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text="Mara meets Lucy.")
        enqueue = patch("heddle.lifecycle._enqueue")
        enqueue.start()
        self.addCleanup(enqueue.stop)

    def make_folio(self, user):
        return Folio.objects.create(title="Quiet City", work_type="fiction", sponsor=user, author=user, submitted_by=user)

    def add(self, main, *variants, folio=None, note="", state="active", shape="writing.character"):
        folio = folio or self.folio
        owner = folio.author
        entity = Entity.objects.create(kind="character", name=main[:255], sponsor=owner, created_by=owner)
        return FolioDictionaryEntry.objects.create(folio=folio, entity=entity, shape_id=shape, shape_version="0.2.0",
            main_name=main, variants=list(variants), note=note, state=state, created_by=owner)

    def open(self):
        return open_dictionary(author=self.user, folio_id=self.folio.pk)

    def begin(self):
        return begin_reading(author=self.user, folio_id=self.folio.pk, note_id=self.note.pk,
            request_id=uuid4(), reading=rec.make_reading())

    def context(self):
        self.folio.refresh_from_db()
        parent = SimpleNamespace(request_payload={"folio_source": {"folio_id": str(self.folio.pk), "note_id": str(self.note.pk)}})
        return rec.context_provider(self.user, parent)

    # Opening

    def test_entries_alone_do_not_make_a_dictionary(self):
        self.add("Mara")
        self.assertIsNone(provider.provide(self.user, self.folio))
        with self.assertRaisesMessage(InterpretationError, "dictionary_unavailable"):
            self.begin()

    def test_open_is_deliberate_owner_only_and_safe_to_repeat(self):
        with self.assertRaisesMessage(InterpretationError, "not_found"):
            open_dictionary(author=self.other, folio_id=self.folio.pk)
        first = self.open()
        self.assertEqual((first["opened"], first["dictionary_revision"], first["context_revision"]), (True, 0, 1))
        again = self.open()
        self.assertEqual((again["opened"], again["dictionary_revision"], again["context_revision"]), (False, 0, 1))
        self.assertEqual(self.context()["dictionary"], {"revision": 0, "entries": []})
        self.begin()  # an opened, empty Dictionary no longer refuses

    def test_owner_command_opens_and_refuses_strangers(self):
        out = StringIO()
        call_command("open_folio_dictionary", str(self.folio.pk), "--author", self.user.username, stdout=out)
        self.assertIn("Opened an empty Dictionary", out.getvalue())
        call_command("open_folio_dictionary", str(self.folio.pk), "--author", self.user.username, stdout=out)
        self.assertIn("nothing changed", out.getvalue())
        for folio_id, author in ((self.folio.pk, self.other.username), (self.folio.pk, "nobody"), ("not-a-uuid", self.user.username)):
            with self.assertRaises(CommandError):
                call_command("open_folio_dictionary", str(folio_id), "--author", author, stdout=out)

    # The slim snapshot

    def test_snapshot_is_slim_and_the_note_never_reaches_the_wire(self):
        self.open()
        mara = self.add("Mara Okafor", "Mara", note="PRIVATE-NOTE she is based on my sister")
        lucy = self.add("Lucy", shape="writing.setting")
        first, second = sorted([mara, lucy], key=lambda e: str(e.pk))
        served = provider.provide(self.user, self.folio)
        self.assertEqual(served["entries"][0], {"entry_id": str(first.pk), "revision": 1, "shape_id": first.shape_id,
            "shape_version": "0.2.0", "names": {"main": first.main_name, "variants": first.variants}})
        self.assertEqual([e["entry_id"] for e in served["entries"]], [str(first.pk), str(second.pk)])
        context = self.context()
        self.assertEqual(context["dictionary"], served)
        self.assertNotIn("PRIVATE-NOTE", wire.canonical(context).decode("utf-8"))

    def test_stored_spelling_is_served_untouched(self):
        self.open()
        self.add("Cafe\u0301  STRASSE", " Mara ")
        names = provider.provide(self.user, self.folio)["entries"][0]["names"]
        self.assertEqual(names, {"main": "Cafe\u0301  STRASSE", "variants": [" Mara "]})

    def test_only_this_folios_active_entries_are_served(self):
        self.open()
        kept = self.add("Mara")
        self.add("Removed", state="removed")
        gone = self.add("Deleted")
        FolioDictionaryEntry.objects.filter(pk=gone.pk).update(deleted_at=timezone.now())
        elsewhere = self.make_folio(self.user)
        open_dictionary(author=self.user, folio_id=elsewhere.pk)
        self.add("Elsewhere", folio=elsewhere)
        theirs = self.make_folio(self.other)
        open_dictionary(author=self.other, folio_id=theirs.pk)
        self.add("Theirs", folio=theirs)
        self.assertEqual([e["entry_id"] for e in provider.provide(self.user, self.folio)["entries"]], [str(kept.pk)])
        self.assertIsNone(provider.provide(self.user, theirs))

    def test_a_revision_that_moves_during_the_read_is_not_served_as_settled(self):
        self.open()
        with patch.object(provider, "_revision", side_effect=[0, 1, 1, 1]):
            self.assertEqual(provider.current_snapshot(self.folio)["revision"], 1)
        with patch.object(provider, "_revision", side_effect=range(6)), self.assertLogs(provider.logger, "ERROR"):
            self.assertIsNone(provider.current_snapshot(self.folio))

    # Records

    def test_same_spelling_may_name_two_entities_but_one_entity_has_one_active_entry(self):
        first = self.add("Mara")
        self.add("Mara")
        with self.assertRaises(IntegrityError), transaction.atomic():
            FolioDictionaryEntry.objects.create(folio=self.folio, entity=first.entity, shape_id=first.shape_id,
                shape_version="0.2.0", main_name="Mara again")
        FolioDictionaryEntry.objects.filter(pk=first.pk).update(state="removed")
        FolioDictionaryEntry.objects.create(folio=self.folio, entity=first.entity, shape_id=first.shape_id,
            shape_version="0.2.0", main_name="Mara again")

    def test_entry_revisions_are_write_once(self):
        entry = self.add("Mara")
        record = FolioDictionaryEntryRevision.objects.create(entry=entry, revision=1, value={"names": {"main": "Mara"}},
            operation="add", actor=self.user, operation_id=uuid4(), recorded_at=timezone.now(), dictionary_revision=1)
        record.value = {"names": {"main": "Changed"}}
        with self.assertRaises(ValueError):
            record.save()
        with self.assertRaises(ValueError):
            record.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            FolioDictionaryEntryRevision.objects.create(entry=entry, revision=1, value={}, operation="edit",
                actor=self.user, operation_id=uuid4(), recorded_at=timezone.now(), dictionary_revision=2)

    # The size guard

    def fill_to_budget(self):
        """Store a Dictionary whose slim snapshot is exactly the write-time budget."""
        self.open()
        specs = []
        measure = lambda: budget.projected_snapshot_size(0, [
            {"entry_id": str(uuid4()), "revision": 1, "shape_id": "writing.character", "shape_version": "0.2.0",
             "names": {"main": main, "variants": variants}} for main, variants in specs])
        while True:
            specs.append(("n" * 200, []))
            if measure() > budget.SNAPSHOT_BUDGET - 600:
                break
        specs[-1][1].append("v")
        specs[-1][1][0] = "v" * (1 + budget.SNAPSHOT_BUDGET - measure())
        for main, variants in specs:
            self.add(main, *variants)
        served = provider.provide(self.user, self.folio)
        self.assertEqual(budget.projected_snapshot_size(served["revision"], served["entries"]), budget.SNAPSHOT_BUDGET)
        return served

    def worst_rest_of_context(self):
        # The longest title the model allows, in the costliest characters, and the largest revision.
        Folio.objects.filter(pk=self.folio.pk).update(title="\x01" * 255, context_revision=2_000_000_000)

    def test_budget_derives_from_the_readings_own_cap(self):
        self.assertEqual(budget.SNAPSHOT_BUDGET, CAP - budget.CONTEXT_RESERVE)
        self.assertEqual(budget.projected_snapshot_size(0, []), size({"revision": 0, "entries": []}))

    def test_reserve_covers_the_worst_rest_of_the_context(self):
        self.open()
        self.worst_rest_of_context()
        context = self.context()
        rest = size(context) - size(context["dictionary"])
        self.assertLessEqual(rest * 2, budget.CONTEXT_RESERVE, "the context grew: raise CONTEXT_RESERVE")

    def test_a_dictionary_at_the_write_budget_always_passes_the_reading_cap(self):
        served = self.fill_to_budget()
        self.assertEqual(budget.check_budget(served["revision"], served["entries"]), budget.SNAPSHOT_BUDGET)
        self.worst_rest_of_context()
        self.assertLessEqual(size(self.context()), CAP)
        snap = self.begin()
        with self.captureOnCommitCallbacks(execute=True):
            result = lifecycle.execute(author=self.user, action_run_id=snap["action_run_id"], request_id=uuid4(),
                expected_revision=snap["revision"], digest=snap["source_digest"],
                expected_context_revision=snap["context_revision"], context_digest=snap["context_digest"],
                reading=rec.make_reading(), consent=False)
        request = ActionRun.objects.get(pk=result["execution_action_run_id"]).request_payload["capability_payload"]
        wire.validate_request(request)  # the reading-time backstop accepts it
        self.assertEqual(request["context"]["dictionary"], served)

    def test_one_character_over_the_budget_is_refused_at_the_edit(self):
        served = self.fill_to_budget()
        grown = [dict(e, names={"main": e["names"]["main"] + "x", "variants": e["names"]["variants"]}) if i == 0 else e
                 for i, e in enumerate(served["entries"])]
        with self.assertRaises(budget.DictionaryFull) as refused:
            budget.check_budget(served["revision"], grown)
        error = refused.exception
        self.assertEqual((error.code, error.status, error.size, error.budget),
                         ("dictionary_full", 413, budget.SNAPSHOT_BUDGET + 1, budget.SNAPSHOT_BUDGET))
        self.assertIn("Shorten or remove", error.message)

    def test_escapes_cost_what_the_reading_charges(self):
        plain = {"entry_id": str(uuid4()), "revision": 1, "shape_id": "s", "shape_version": "0.2.0",
                 "names": {"main": "a", "variants": []}}
        control = dict(plain, names={"main": "\x01", "variants": []})
        self.assertEqual(budget.projected_snapshot_size(0, [control]) - budget.projected_snapshot_size(0, [plain]), 5)
