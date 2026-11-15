"""The registered Dictionary provider: shape, scoping and refusal."""
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from folio.dictionary import provider
from folio.interpretation import recognition as rec
from folio.interpretation.lifecycle import begin_reading
from folio.models import Folio, FolioNote
from heddle.errors import InterpretationError


def entry(main="Mara", **changes):
    value = {"entry_id": str(uuid4()), "revision": 1, "shape_id": "writing.character", "shape_version": "0.2.0",
             "names": {"main": main, "variants": []}}
    value.update(changes)
    return value


@override_settings(FOLIO_RECOGNITION_ENABLED=True)
class DictionaryProviderTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.user = users.create_user(username="dictionary-writer")
        self.other = users.create_user(username="dictionary-other")
        self.folio = Folio.objects.create(title="Quiet City", work_type="fiction",
            sponsor=self.user, author=self.user, submitted_by=self.user)
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text="Mara meets Lucy.")
        enqueue = patch("heddle.lifecycle._enqueue")
        enqueue.start()
        self.addCleanup(enqueue.stop)

    def begin(self):
        return begin_reading(author=self.user, folio_id=self.folio.pk, note_id=self.note.pk,
            request_id=uuid4(), reading=rec.make_reading())

    def stored(self, snapshot):
        return patch.object(provider, "current_snapshot", return_value=snapshot)

    def test_registered_at_app_start(self):
        self.assertIs(rec._dictionary_provider, provider.provide)

    def test_folio_without_a_dictionary_still_refuses(self):
        self.assertIsNone(provider.provide(self.user, self.folio))
        with self.assertRaisesMessage(InterpretationError, "dictionary_unavailable"):
            self.begin()

    def test_no_registered_provider_refuses(self):
        with patch.object(rec, "_dictionary_provider", None):
            with self.assertRaisesMessage(InterpretationError, "dictionary_unavailable"):
                self.begin()

    def test_returns_the_exact_shape_in_a_stable_order(self):
        first, second = sorted([entry("Mara"), entry("Lucy")], key=lambda e: e["entry_id"])
        with self.stored({"revision": 3, "entries": [second, first]}) as store:
            result = provider.provide(self.user, self.folio)
            store.assert_called_once_with(self.folio)
            self.begin()  # core accepts it: no refusal
        self.assertEqual(result, {"revision": 3, "entries": [first, second]})

    def test_an_existing_empty_dictionary_is_returned_as_empty(self):
        with self.stored({"revision": 0, "entries": []}):
            self.assertEqual(provider.provide(self.user, self.folio), {"revision": 0, "entries": []})

    def test_another_members_folio_never_leaks(self):
        with self.stored({"revision": 1, "entries": [entry()]}) as store:
            self.assertIsNone(provider.provide(self.other, self.folio))
            store.assert_not_called()

    def test_deleted_folio_is_not_served(self):
        Folio.objects.filter(pk=self.folio.pk).update(deleted_at=timezone.now())
        with self.stored({"revision": 1, "entries": [entry()]}) as store:
            self.assertIsNone(provider.provide(self.user, self.folio))
            store.assert_not_called()

    def test_malformed_storage_is_refused_not_repaired(self):
        same = entry()
        for snapshot in (
            [], {"revision": 1}, {"revision": -1, "entries": []}, {"revision": True, "entries": []},
            {"revision": 1, "entries": [entry(revision=0)]}, {"revision": 1, "entries": [entry(entry_id="mara")]},
            {"revision": 1, "entries": [entry(names={"main": " ", "variants": []})]},
            {"revision": 1, "entries": [entry(folio_id="x")]}, {"revision": 1, "entries": [same, dict(same)]},
            {"revision": 1, "entries": [entry(note="private")]}, {"revision": 1, "entries": [entry(shape_id="")]},
        ):
            with self.subTest(snapshot=snapshot), self.stored(snapshot), self.assertLogs(provider.logger, "ERROR"):
                self.assertIsNone(provider.provide(self.user, self.folio))
                with self.assertRaisesMessage(InterpretationError, "dictionary_unavailable"):
                    self.begin()
