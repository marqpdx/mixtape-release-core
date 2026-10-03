# folio/tests/test_notes.py
#
# Folio Notes PoC — capture spine (mobile-first build order steps 1–2,
# puddlejump/decisions/folio/folio-notes-poc-mobile-handoff.md). No Inkwell
# or Whisper dependency: storage, transcription, and the Livewire notify are
# all mocked, so these run anywhere the test DB does.

from types import SimpleNamespace
from unittest.mock import patch

from celery.exceptions import Retry

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from files.models import StoredFile
from folio.models import Folio, FolioNote, FolioNoteSource, FolioNoteStatus
from folio.shapes import Shape, effective_shape
from folio.tasks import apply_folio_note_tending, tend_folio_note_task, transcribe_folio_note_task
from initiatives.models import ActionRun, ActionRunStatus

User = get_user_model()


class FolioNoteCaptureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="folio_notes_writer")
        self.other = User.objects.create_user(username="folio_notes_other")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.folio = Folio.objects.create(title="The Quiet City", created_by=self.user)
        tend_patcher = patch("folio.api.views.tend_folio_note_task.delay")
        self.tend_delay = tend_patcher.start()
        self.addCleanup(tend_patcher.stop)

    def _notes_url(self, folio=None):
        return f"/api/folio/folios/{(folio or self.folio).id}/notes"

    def test_list_and_create_folios_scoped_to_owner(self):
        Folio.objects.create(title="Not mine", created_by=self.other)
        response = self.client.post("/api/folio/folios", {"title": "Second"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.get("/api/folio/folios")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({f["title"] for f in response.data}, {"The Quiet City", "Second"})

    def test_text_note_is_ready_immediately_and_preserves_exact_input(self):
        raw = "  Character Jode. His grandmother couldn't care for herself.  "
        response = self.client.post(self._notes_url(), {"raw_text": raw, "source": "mobile"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["source_type"], "text")
        self.assertEqual(response.data["status"], "ready")
        self.assertEqual(response.data["raw_text"], raw)
        self.assertEqual(response.data["text"], raw)
        self.assertEqual(response.data["shape"], "unplaced")
        self.tend_delay.assert_called_once_with(response.data["id"])

    @patch("folio.api.views.transcribe_folio_note_task.delay")
    @patch("folio.api.views.default_storage.save", return_value="folio/notes/audio/test/voice.m4a")
    def test_voice_note_persists_before_transcription(self, _save_mock, delay_mock):
        response = self.client.post(
            self._notes_url(),
            {"audio_file": SimpleUploadedFile("voice.m4a", b"a" * 128, content_type="audio/m4a"), "source": "mobile"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["source_type"], "voice")
        self.assertEqual(response.data["status"], "processing")
        self.assertTrue(response.data["has_audio"])

        note = FolioNote.objects.get(id=response.data["id"])
        self.assertEqual(note.audio_file.file_path, "folio/notes/audio/test/voice.m4a")
        delay_mock.assert_called_once_with(str(note.id))

    def test_rejects_non_audio_upload(self):
        response = self.client.post(
            self._notes_url(),
            {"audio_file": SimpleUploadedFile("x.txt", b"hi", content_type="text/plain")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(FolioNote.objects.exists())

    def test_cannot_read_or_write_another_writers_folio(self):
        theirs = Folio.objects.create(title="Theirs", created_by=self.other)
        self.assertEqual(self.client.get(self._notes_url(theirs)).status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.post(self._notes_url(theirs), {"raw_text": "hello"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_returns_newest_first(self):
        for text in ("first", "second"):
            self.client.post(self._notes_url(), {"raw_text": text}, format="json")
        response = self.client.get(self._notes_url())
        self.assertEqual([n["text"] for n in response.data], ["second", "first"])


class FolioNoteTranscriptionTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="folio_notes_task_writer")
        self.folio = Folio.objects.create(title="", created_by=self.user)
        stored = StoredFile.objects.create(file_path="folio/notes/audio/x.m4a", uploaded_by=self.user)
        self.note = FolioNote.objects.create(
            folio=self.folio,
            created_by=self.user,
            source_type=FolioNoteSource.VOICE,
            audio_file=stored,
            status=FolioNoteStatus.PROCESSING,
        )

    @patch("folio.tasks.tend_folio_note_task.delay")
    @patch("folio.tasks.requests.post")
    @patch("folio.tasks.transcribe_audio")
    def test_transcription_marks_ready_notifies_and_queues_tending(self, transcribe_mock, notify_mock, tend_delay):
        transcribe_mock.return_value = SimpleNamespace(text=" Joad was motivated. ", model_name="base", backend="faster-whisper")
        transcribe_folio_note_task.apply(args=[str(self.note.id)])

        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FolioNoteStatus.READY)
        self.assertEqual(self.note.transcript_text, "Joad was motivated.")
        self.assertEqual(self.note.text, "Joad was motivated.")
        self.assertEqual(notify_mock.call_args.kwargs["json"]["event"], "folio_note:transcribed")
        tend_delay.assert_called_once_with(str(self.note.id))

    @patch("folio.tasks.transcribe_audio", side_effect=RuntimeError("whisper down"))
    def test_transcription_failure_keeps_the_audio(self, _transcribe_mock):
        # Stop at the first retry — exhausting eager retries trips the global
        # task-failure logger, which isn't what this test is about.
        with patch.object(transcribe_folio_note_task, "retry", side_effect=Retry()):
            with self.assertRaises(Retry):
                transcribe_folio_note_task.run(str(self.note.id))

        self.note.refresh_from_db()
        self.assertEqual(self.note.status, FolioNoteStatus.FAILED)
        self.assertIn("whisper down", self.note.transcript_error)
        self.assertIsNotNone(self.note.audio_file_id)


class ShapeSeamTests(TestCase):
    def test_confirmed_wins_over_suggested_and_default_is_unplaced(self):
        self.assertEqual(effective_shape("plot", "character"), Shape.CHARACTER)
        self.assertEqual(effective_shape("plot", ""), Shape.PLOT)
        self.assertEqual(effective_shape("", ""), Shape.UNPLACED)


class FolioNoteTendingTests(TestCase):
    """Core side of Switchboard → Inkwell `folio_note_tend`: dispatch records an
    ActionRun; the callback projects it onto the note without touching human
    or raw fields."""

    def setUp(self):
        self.user = User.objects.create_user(username="folio_notes_tend_writer")
        self.folio = Folio.objects.create(title="The Quiet City", created_by=self.user)
        self.note = FolioNote.objects.create(
            folio=self.folio,
            created_by=self.user,
            source_type=FolioNoteSource.TEXT,
            raw_text="Character Jode. His grandmother could not care for herself.",
        )

    @patch("folio.tasks.celery_app.send_task")
    def test_dispatch_records_action_run_and_sends_capability(self, send_task):
        tend_folio_note_task.apply(args=[str(self.note.id)])

        self.note.refresh_from_db()
        run = self.note.tending_action_run
        self.assertEqual(run.tool_name, "capability.folio_note_tend")
        self.assertEqual(run.status, ActionRunStatus.PENDING)
        kwargs = send_task.call_args.kwargs["kwargs"]
        self.assertEqual(send_task.call_args.args[0], "switchboard.capability_async")
        self.assertEqual(send_task.call_args.kwargs["queue"], "switchboard")
        self.assertEqual(kwargs["action_run_id"], str(run.id))
        self.assertEqual(kwargs["capability_payload"]["allowed_shapes"], list(Shape.values))
        self.assertEqual(kwargs["callback_task"], "folio.tasks.apply_folio_note_tending")

    @patch("folio.tasks.celery_app.send_task")
    def test_dispatch_skips_notes_without_text(self, send_task):
        self.note.raw_text = "   "
        self.note.save()
        tend_folio_note_task.apply(args=[str(self.note.id)])
        send_task.assert_not_called()
        self.assertFalse(ActionRun.objects.exists())

    def _finished_run(self, *, status, result=None, error=None):
        run = ActionRun.objects.create(
            tool_name="capability.folio_note_tend",
            status=status,
            tenant_id="00000000-0000-0000-0000-000000000001",
            tenant_namespace="platform:crossroads",
            initiator_type="system",
            initiator_id=str(self.user.pk),
            result_payload={"result": result} if result else None,
            error_payload=error,
        )
        self.note.tending_action_run = run
        self.note.save()
        return run

    @patch("folio.tasks.requests.post")
    def test_callback_applies_suggestion_but_never_overrides_confirmation(self, notify_mock):
        self.note.confirmed_shape = Shape.META
        self.note.save()
        run = self._finished_run(
            status=ActionRunStatus.SUCCEEDED,
            result={
                "shape": "character",
                "shape_confidence": 0.82,
                "summary": "Jode's motive.",
                "mentions": [{"surface": "Jode", "kind": "character"}],
                "provenance": {"model": "Phi-3.5-mini-instruct-Q4_K_M", "prompt_version": "folio_note_tending_v1"},
            },
        )
        apply_folio_note_tending.apply(args=[str(run.id)])

        self.note.refresh_from_db()
        self.assertEqual(self.note.suggested_shape, Shape.CHARACTER)
        self.assertEqual(self.note.confirmed_shape, Shape.META)
        self.assertEqual(self.note.shape, Shape.META)
        self.assertEqual(self.note.tending_model, "Phi-3.5-mini-instruct-Q4_K_M")
        self.assertEqual(self.note.tending_prompt_version, "folio_note_tending_v1")
        self.assertEqual(self.note.mentions, [{"surface": "Jode", "kind": "character"}])
        self.assertIsNotNone(self.note.tended_at)
        self.assertEqual(self.note.raw_text, "Character Jode. His grandmother could not care for herself.")
        self.assertEqual(notify_mock.call_args.kwargs["json"]["event"], "folio_note:tended")

    def test_callback_coerces_unknown_shape_to_unplaced(self):
        run = self._finished_run(status=ActionRunStatus.SUCCEEDED, result={"shape": "theme", "provenance": {}})
        with patch("folio.tasks.requests.post"):
            apply_folio_note_tending.apply(args=[str(run.id)])
        self.note.refresh_from_db()
        self.assertEqual(self.note.suggested_shape, Shape.UNPLACED)

    def test_failed_run_records_error_and_leaves_note_usable(self):
        run = self._finished_run(status=ActionRunStatus.FAILED, error={"error": "InkwellUnavailable", "message": "inkwell down"})
        apply_folio_note_tending.apply(args=[str(run.id)])
        self.note.refresh_from_db()
        self.assertEqual(self.note.tending_error, "inkwell down")
        self.assertEqual(self.note.suggested_shape, "")
        self.assertEqual(self.note.shape, Shape.UNPLACED)

    def test_stale_callback_from_superseded_run_is_ignored(self):
        old_run = self._finished_run(status=ActionRunStatus.SUCCEEDED, result={"shape": "plot", "provenance": {}})
        self._finished_run(status=ActionRunStatus.PENDING)
        result = apply_folio_note_tending.apply(args=[str(old_run.id)]).get()
        self.assertEqual(result["status"], "stale")
        self.note.refresh_from_db()
        self.assertEqual(self.note.suggested_shape, "")
