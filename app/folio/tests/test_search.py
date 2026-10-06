# folio/tests/test_search.py
#
# Folio Notes PoC Phase 4 — retrieval (folio-notes-poc-handoff.md addendum §3).
# Stackroom is mocked: these cover the FolioNote adapter, ingest wiring, and
# the Postgres-side filtering/ranking around Stackroom's semantic match.

import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from folio.models import Folio, FolioNote, FolioNoteSource
from folio.shapes import Shape
from inkwell.models import StackroomSyncState
from inkwell.stackroom_adapters import get_adapter
from inkwell.stackroom_integration_service import ingest_object
from stackroom_client import StackroomClientError

User = get_user_model()


class FolioNoteSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="folio_search_writer")
        self.user.stackroom_library_id = uuid.uuid4()
        self.user.save(update_fields=["stackroom_library_id"])
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.folio = Folio.objects.create(title="The Quiet City", created_by=self.user)
        self.other_folio = Folio.objects.create(title="Elsewhere", created_by=self.user)
        self.note_ct = ContentType.objects.get_for_model(FolioNote, for_concrete_model=False)

    def _note(self, text, *, folio=None, suggested="", confirmed="", mentions=None):
        return FolioNote.objects.create(
            folio=folio or self.folio,
            created_by=self.user,
            source_type=FolioNoteSource.TEXT,
            raw_text=text,
            suggested_shape=suggested,
            confirmed_shape=confirmed,
            mentions=mentions or [],
        )

    def _synced(self, note):
        source_file_id = uuid.uuid4()
        StackroomSyncState.objects.create(
            content_type=self.note_ct,
            object_id=str(note.pk),
            adapter_name="folio_note",
            status=StackroomSyncState.STATUS_SYNCED,
            stackroom_source_file_id=source_file_id,
        )
        return str(source_file_id)

    def _search(self, **params):
        return self.client.get(f"/api/folio/folios/{self.folio.id}/notes/search", params)

    # --- ingest side ---

    def test_adapter_embeds_note_text_only_with_folio_note_artifact_type(self):
        note = self._note("Jode's grandmother keeps the lighthouse key.", suggested=Shape.CHARACTER)
        adapter = get_adapter(note)
        self.assertEqual(adapter.adapter_name, "folio_note")
        self.assertEqual(adapter.artifact_type, "folio_note")
        self.assertEqual(adapter.build_text(note), "Jode's grandmother keeps the lighthouse key.")

        with patch("inkwell.stackroom_integration_service.ingest_text") as ingest_text:
            ingest_text.return_value = {"source_file_id": str(uuid.uuid4()), "hash_sha256": "h"}
            sync_state = ingest_object(note, reason="test")
        self.assertEqual(ingest_text.call_args.kwargs["artifact_type"], "folio_note")
        self.assertEqual(ingest_text.call_args.kwargs["library_id"], self.user.stackroom_library_id)
        self.assertEqual(sync_state.status, StackroomSyncState.STATUS_SYNCED)

    def test_text_capture_enqueues_stackroom_ingest(self):
        with patch("folio.api.views.tend_folio_note_task.delay"), patch(
            "inkwell.tasks.stackroom_integration.ingest_object_task.apply_async"
        ) as apply_async, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/folio/folios/{self.folio.id}/notes", {"raw_text": "A note."}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(apply_async.call_args.kwargs["kwargs"]["object_id"], response.data["id"])

    # --- recent mode (no q) ---

    def test_recent_mode_filters_by_effective_shape(self):
        suggested_place = self._note("harbor", suggested=Shape.SETTING)
        overridden = self._note("corrected", suggested=Shape.SETTING, confirmed=Shape.CHARACTER)
        unplaced = self._note("loose thought")
        self._note("wrong folio", folio=self.other_folio, suggested=Shape.SETTING)

        response = self._search(shape="setting")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["mode"], "recent")
        self.assertEqual([r["id"] for r in response.data["results"]], [str(suggested_place.id)])

        response = self._search(shape="character")
        self.assertEqual([r["id"] for r in response.data["results"]], [str(overridden.id)])

        response = self._search(shape="unplaced")
        self.assertEqual([r["id"] for r in response.data["results"]], [str(unplaced.id)])

    def test_entity_filter_counts_only_confirmed_links(self):
        entity_id = str(uuid.uuid4())
        confirmed = self._note("Jode again", mentions=[
            {"surface": "Jode", "kind": "character", "confirmed_entity_id": entity_id},
        ])
        self._note("Jode, unconfirmed", mentions=[
            {"surface": "Jode", "kind": "character", "existing_entity_id": entity_id},
        ])
        response = self._search(entity=entity_id)
        self.assertEqual([r["id"] for r in response.data["results"]], [str(confirmed.id)])

    def test_invalid_shape_and_entity_are_rejected(self):
        self.assertEqual(self._search(shape="villain").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._search(entity="nope").status_code, status.HTTP_400_BAD_REQUEST)

    # --- semantic mode ---

    def test_semantic_mode_ranks_by_stackroom_score_within_folio_and_filters(self):
        best = self._note("the lighthouse at dusk", suggested=Shape.SETTING)
        second = self._note("lamp oil and salt", suggested=Shape.SETTING)
        wrong_shape = self._note("lighthouse keeper's temper", suggested=Shape.CHARACTER)
        elsewhere = self._note("another lighthouse", folio=self.other_folio, suggested=Shape.SETTING)
        sf = {n.pk: self._synced(n) for n in (best, second, wrong_shape, elsewhere)}

        stackroom_results = [
            {"source_file_id": sf[elsewhere.pk], "score": 0.95},
            {"source_file_id": sf[wrong_shape.pk], "score": 0.9},
            {"source_file_id": sf[second.pk], "score": 0.4},
            {"source_file_id": sf[best.pk], "score": 0.8},
            {"source_file_id": sf[best.pk], "score": 0.2},  # a second chunk of the same note
            {"source_file_id": str(uuid.uuid4()), "score": 0.99},  # not a FolioNote of ours
        ]
        with patch("folio.services.note_search.retrieve", return_value=stackroom_results) as retrieve:
            response = self._search(q="lighthouse", shape="setting")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["mode"], "semantic")
        self.assertEqual([r["id"] for r in response.data["results"]], [str(best.id), str(second.id)])
        self.assertEqual(response.data["results"][0]["score"], 0.8)
        self.assertEqual(retrieve.call_args.kwargs["artifact_types"], ["folio_note"])
        self.assertEqual(retrieve.call_args.kwargs["library_id"], self.user.stackroom_library_id)

    def test_semantic_mode_without_library_returns_nothing(self):
        self.user.stackroom_library_id = None
        self.user.save(update_fields=["stackroom_library_id"])
        self._note("anything")
        with patch("folio.services.note_search.retrieve") as retrieve:
            response = self._search(q="anything")
        self.assertEqual(response.data["results"], [])
        retrieve.assert_not_called()

    def test_stackroom_failure_is_a_503_not_a_crash(self):
        with patch(
            "folio.services.note_search.retrieve",
            side_effect=StackroomClientError("Stackroom unreachable", status_code=502),
        ):
            response = self._search(q="lighthouse")
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_other_writers_folio_is_not_searchable(self):
        other = User.objects.create_user(username="folio_search_other")
        folio = Folio.objects.create(title="Theirs", created_by=other)
        response = self.client.get(f"/api/folio/folios/{folio.id}/notes/search")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
