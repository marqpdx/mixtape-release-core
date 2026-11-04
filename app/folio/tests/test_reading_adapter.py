from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from folio.models import Folio, FolioNote, FolioInterpretation
from folio.interpretation.lifecycle import begin_reading, inspect_reading, context_provider
from folio.interpretation.strategy import make_reading
from folio.tasks import transcribe_folio_note_task
from heddle import lifecycle
from heddle.errors import InterpretationError
from initiatives.models import ActionRun


class FolioReadingAdapterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="reading-writer")
        self.other = get_user_model().objects.create_user(username="reading-other")
        self.folio = Folio.objects.create(title="Jackalope", work_type="fiction",
            sponsor=self.user, author=self.user, submitted_by=self.user)
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text="locale is desert southwest; main character is Travis.")
        self.reading = make_reading(capability="test_fiction_reading", context_provider=context_provider)

    def begin(self, **overrides):
        args = dict(author=self.user, folio_id=self.folio.pk, note_id=self.note.pk,
            request_id=uuid4(), reading=self.reading)
        args.update(overrides)
        return begin_reading(**args)

    def test_begin_is_bounded_capture_snapshot_not_execution(self):
        result = self.begin()
        self.assertEqual(result["sources"][0]["text"], self.note.raw_text)
        self.assertNotIn("weave_action_run_id", result)
        self.assertIn("reading_id", result)
        self.assertEqual(result["context"]["strategy_id"], "writing.fiction_note_reading")
        self.assertEqual(result["steps"], [])
        self.assertEqual(ActionRun.objects.count(), 1)
        self.assertEqual(FolioInterpretation.objects.count(), 1)

    def test_begin_reuses_one_chain_without_new_parent(self):
        first = self.begin()
        second = self.begin()
        self.assertEqual(first["reading_id"], second["reading_id"])
        self.assertEqual(ActionRun.objects.count(), 1)

    def test_untyped_or_unready_capture_cannot_start(self):
        self.folio.work_type = ""
        self.folio.save()
        with self.assertRaises(InterpretationError): self.begin()
        self.folio.work_type = "fiction"
        self.folio.save()
        self.note.status = "processing"
        self.note.save()
        with self.assertRaises(InterpretationError): self.begin()
        self.assertFalse(ActionRun.objects.exists())

    def test_other_member_cannot_begin_or_inspect(self):
        result = self.begin()
        with self.assertRaises(InterpretationError): self.begin(author=self.other)
        with self.assertRaises(InterpretationError):
            inspect_reading(author=self.other, folio_id=self.folio.pk, note_id=self.note.pk,
                reading_id=result["reading_id"], reading=self.reading)

    def test_original_capture_is_immutable_after_reading(self):
        self.begin()
        self.note.raw_text = "changed"
        with self.assertRaises(ValueError): self.note.save(update_fields=["raw_text"])
        self.note.refresh_from_db()
        self.assertIn("Travis", self.note.raw_text)
        self.note.confirmed_shape = "character"
        self.note.save(update_fields=["confirmed_shape"])

    def test_shared_correction_is_append_only_and_never_runs_a_model(self):
        result = self.begin()
        corrected = lifecycle.correct(author=self.user, action_run_id=result["action_run_id"],
            request_id=uuid4(), expected_revision=0, reading=self.reading, text="His name is Trevor.")
        self.note.refresh_from_db()
        self.assertIn("Travis", self.note.raw_text)
        self.assertEqual(len(corrected["sources"]), 2)
        self.assertEqual(corrected["sources"][0]["text"], self.note.raw_text)
        self.assertEqual(ActionRun.objects.count(), 1)

    def test_move_invalidates_original_parent_context(self):
        result = self.begin()
        target = Folio.objects.create(title="Other", work_type="fiction", sponsor=self.user,
            author=self.user, submitted_by=self.user)
        self.note.folio = target
        self.note.save(update_fields=["folio"])
        parent = ActionRun.objects.get(pk=result["action_run_id"])
        with self.assertRaises(InterpretationError): context_provider(self.user, parent)
        with self.assertRaises(InterpretationError):
            inspect_reading(author=self.user, folio_id=target.pk, note_id=self.note.pk,
                reading_id=result["reading_id"], reading=self.reading)

    def test_voice_capture_is_not_retranscribed_after_reading(self):
        self.note.source_type = "voice"
        self.note.transcript_text = "Travis in the bar."
        self.note.save()
        self.begin()
        with patch("folio.tasks.transcribe_audio") as transcribe:
            outcome = transcribe_folio_note_task(str(self.note.pk))
        self.assertEqual(outcome["reason"], "source_already_read")
        transcribe.assert_not_called()

    def test_source_budget_failure_creates_no_parent(self):
        self.note.raw_text = "x" * 40001
        self.note.save()
        with self.assertRaises(InterpretationError): self.begin()
        self.assertFalse(ActionRun.objects.exists())
