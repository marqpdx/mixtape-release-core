# folio/tests/test_workbench.py
#
# Folio Notes PoC Phase 5 — Desktop Workbench endpoints: facets, literal
# search, related notes, mention → Entity association, move to Folio.
# Stackroom is mocked.

import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from folio.models import Folio, FolioNote, FolioNoteSource
from folio.services.note_search import NoteHit
from folio.shapes import Shape
from storyboard.models import Entity
from storyboard.services import match_entity_alias

User = get_user_model()


class FolioWorkbenchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="folio_workbench_writer")
        self.other = User.objects.create_user(username="folio_workbench_other")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.folio = Folio.objects.create(title="The Quiet City", created_by=self.user)
        self.base = f"/api/folio/folios/{self.folio.id}/notes"

    def _note(self, text, *, folio=None, suggested="", confirmed="", mentions=None, summary=""):
        return FolioNote.objects.create(
            folio=folio or self.folio,
            created_by=self.user,
            source_type=FolioNoteSource.TEXT,
            raw_text=text,
            suggested_shape=suggested,
            confirmed_shape=confirmed,
            mentions=mentions or [],
            summary=summary,
        )

    def _entity(self, name, kind="character", user=None, aliases=None):
        user = user or self.user
        return Entity.objects.create(
            kind=kind, name=name, aliases=aliases or [], created_by=user,
            sponsor_content_type=ContentType.objects.get_for_model(user), sponsor_object_id=user.pk,
        )

    # --- facets ---

    def test_facets_count_every_shape_and_confirmed_entities(self):
        jode = self._entity("Jode")
        self._note("a", suggested=Shape.CHARACTER, mentions=[
            {"surface": "Jode", "kind": "character", "confirmed_entity_id": str(jode.id)},
            {"surface": "him", "kind": "character", "confirmed_entity_id": str(jode.id)},
        ])
        self._note("b", suggested=Shape.CHARACTER, confirmed=Shape.SCENE)
        self._note("c")

        response = self.client.get(f"{self.base}/facets")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        counts = {row["shape"]: row["count"] for row in response.data["shapes"]}
        self.assertEqual(response.data["total"], 3)
        self.assertEqual(set(counts), set(Shape.values))
        self.assertEqual((counts["character"], counts["scene"], counts["unplaced"], counts["world"]), (1, 1, 1, 0))
        self.assertEqual(response.data["entities"], [
            {"id": str(jode.id), "name": "Jode", "kind": "character", "count": 1},
        ])

    # --- literal search ---

    def test_literal_search_matches_text_and_summary_without_stackroom(self):
        by_text = self._note("The old bridge at night")
        by_summary = self._note("something half-remembered", summary="About the bridge.")
        self._note("unrelated")
        with patch("folio.services.note_search.retrieve") as retrieve:
            response = self.client.get(f"{self.base}/search", {"q": "BRIDGE", "mode": "literal"})
        retrieve.assert_not_called()
        self.assertEqual(response.data["mode"], "literal")
        self.assertEqual({r["id"] for r in response.data["results"]}, {str(by_text.id), str(by_summary.id)})

    # --- related ---

    def test_related_excludes_the_note_itself(self):
        note = self._note("the lighthouse")
        neighbour = self._note("lamp oil")
        with patch("folio.services.workbench.search_folio_notes",
                   return_value=[NoteHit(note, 1.0), NoteHit(neighbour, 0.7)]) as search:
            response = self.client.get(f"{self.base}/{note.id}/related")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([r["id"] for r in response.data["results"]], [str(neighbour.id)])
        self.assertEqual(search.call_args.kwargs["query"], "the lighthouse")

    # --- mention association ---

    def test_confirm_mention_as_new_entity_shared_with_storyboard_matching(self):
        note = self._note("Grandmother kept the key", mentions=[
            {"surface": "Grandmother", "kind": "character", "confidence": 0.8, "existing_entity_id": None},
        ])
        response = self.client.post(f"{self.base}/{note.id}/mentions/0", {"name": "Nana Ruth"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mention = response.data["mentions"][0]
        entity = Entity.objects.get(pk=mention["confirmed_entity_id"])
        self.assertEqual((entity.name, entity.kind, entity.aliases), ("Nana Ruth", "character", ["Grandmother"]))
        self.assertEqual(mention["confidence"], 0.8)  # model's view kept for provenance
        # Next tending pass will suggest the same Entity for "Grandmother".
        self.assertEqual(match_entity_alias(
            sponsor_content_type=ContentType.objects.get_for_model(self.user),
            sponsor_object_id=self.user.pk, kind="character", surface="grandmother",
        ), entity)

    def test_confirm_mention_to_existing_entity_and_unlink(self):
        jode = self._entity("Jode")
        note = self._note("Jode ran", mentions=[{"surface": "Jode", "kind": "character"}])
        response = self.client.post(f"{self.base}/{note.id}/mentions/0", {"entity_id": str(jode.id)}, format="json")
        self.assertEqual(response.data["mentions"][0]["confirmed_entity_id"], str(jode.id))
        jode.refresh_from_db()
        self.assertEqual(jode.aliases, [])  # surface already is the name

        response = self.client.delete(f"{self.base}/{note.id}/mentions/0")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("confirmed_entity_id", response.data["mentions"][0])

    def test_cannot_link_another_writers_entity_or_a_missing_mention(self):
        theirs = self._entity("Theirs", user=self.other)
        note = self._note("x", mentions=[{"surface": "x", "kind": "thing"}])
        response = self.client.post(f"{self.base}/{note.id}/mentions/0", {"entity_id": str(theirs.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.post(f"{self.base}/{note.id}/mentions/3", {"name": "Y"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_writer_entities_list_is_scoped(self):
        self._entity("Jode")
        self._entity("Theirs", user=self.other)
        response = self.client.get("/api/folio/entities")
        self.assertEqual([e["name"] for e in response.data], ["Jode"])

    # --- move ---

    def test_move_note_to_another_of_the_writers_folios(self):
        note = self._note("belongs elsewhere")
        target = Folio.objects.create(title="Second book", created_by=self.user)
        response = self.client.patch(f"{self.base}/{note.id}", {"folio": str(target.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        note.refresh_from_db()
        self.assertEqual(note.folio_id, target.id)

        theirs = Folio.objects.create(title="Not mine", created_by=self.other)
        response = self.client.patch(
            f"/api/folio/folios/{target.id}/notes/{note.id}", {"folio": str(theirs.id)}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_requires_a_field(self):
        note = self._note("x")
        response = self.client.patch(f"{self.base}/{note.id}", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_uuid_routes_still_404(self):
        response = self.client.get(f"{self.base}/{uuid.uuid4()}/related")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
