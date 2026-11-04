from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from folio.models import Folio, FolioNote, FolioInterpretation, FolioSightingDecision
from folio.services.interpretation import (prepare_context, change_orientation,
    confirm_orientation, current_context, decide_sighting)
from heddle.bundle import digest
from heddle.errors import InterpretationError
from heddle.steps import archive
from initiatives.models import ActionRun
from sourcework.models import ProvisionalData


class InterpretationServicesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="fi7-writer")
        self.other = get_user_model().objects.create_user(username="fi7-other")
        self.folio = Folio.objects.create(title="Quiet City", sponsor=self.user,
            author=self.user, submitted_by=self.user, work_type="fiction")
        self.note = FolioNote.objects.create(folio=self.folio, created_by=self.user,
            source_type="text", raw_text="Mara returns.")
        self.context = prepare_context(author=self.user, folio_id=self.folio.pk, expected_revision=0)
        self.attempt = uuid4()
        self.sighting = {"sighting_id": "c1", "shape_id": "writing.character",
            "shape_version": "0.1.0", "name_as_said": "Mara", "confidence": "medium",
            "source_locator": [{"source_ref": "note:1", "source_revision": 0,
                "start": 0, "end": 4, "quote": "Mara"}], "uncertain": []}
        self.state = {"attempt_id": str(self.attempt), "status": "succeeded",
            "revision": 0, "context": self.context, "steps": [],
            "sources": [{"source_ref": "note:1", "source_revision": 0, "text": self.note.text}],
            "findings": {"sightings": [self.sighting]}, "history": []}
        self.parent = ActionRun.objects.create(tool_name="folio.reading", status="pending",
            initiator_type="human", initiator_id=str(self.user.pk),
            tenant_id="00000000-0000-0000-0000-000000000001", tenant_namespace="platform:crossroads",
            request_payload={"interpretation": self.state})
        self.reading = FolioInterpretation.objects.create(folio_note=self.note,
            initiated_by=self.user, action_run=self.parent)

    def command(self, **overrides):
        self.folio.refresh_from_db()
        args = dict(author=self.user, interpretation_id=self.reading.pk,
            attempt_id=self.attempt, sighting_id="c1", request_id=uuid4(),
            disposition="dismiss", reviewed_digest=digest(current_context(self.folio)))
        args.update(overrides)
        return args

    def test_prepare_is_stable_and_owner_scoped(self):
        self.assertEqual(prepare_context(author=self.user, folio_id=self.folio.pk,
            expected_revision=1), self.context)
        with self.assertRaises(InterpretationError):
            prepare_context(author=self.other, folio_id=self.folio.pk, expected_revision=1)

    def test_title_change_advances_context_without_suggesting_reading(self):
        result = change_orientation(author=self.user, folio_id=self.folio.pk,
            expected_revision=1, title="The Quiet City")
        self.assertEqual(result["context"]["revision"], 2)
        self.assertIsNone(result["rereading_suggestion"])
        self.assertEqual(self.note.text, "Mara returns.")

    def test_type_change_suggests_without_dispatch(self):
        result = change_orientation(author=self.user, folio_id=self.folio.pk,
            expected_revision=1, work_type="")
        self.assertTrue(result["rereading_suggestion"])
        self.assertEqual(ActionRun.objects.count(), 1)

    def test_confirmation_does_not_accept_findings(self):
        confirm_orientation(author=self.user, folio_id=self.folio.pk,
            expected_digest=digest(self.context), title="Quiet City", work_type="fiction")
        self.assertEqual(FolioSightingDecision.objects.count(), 0)

    def test_keep_replay_creates_one_record(self):
        command = self.command(disposition="defer")
        first = decide_sighting(**command)
        self.assertEqual(first.pk, decide_sighting(**command).pk)
        self.assertEqual(ProvisionalData.objects.count(), 1)
        with self.assertRaises(InterpretationError):
            decide_sighting(**{**command, "disposition": "dismiss"})

    def test_conflicting_occurrence_is_not_overwritten(self):
        decide_sighting(**self.command())
        with self.assertRaises(InterpretationError):
            decide_sighting(**self.command(disposition="defer"))
        self.assertEqual(ProvisionalData.objects.count(), 0)

    def test_other_person_cannot_decide(self):
        with self.assertRaises(InterpretationError):
            decide_sighting(**self.command(author=self.other))

    def test_old_context_requires_and_records_reaffirmation(self):
        change_orientation(author=self.user, folio_id=self.folio.pk,
            expected_revision=1, title="Renamed City")
        with self.assertRaises(InterpretationError):
            decide_sighting(**self.command())
        decision = decide_sighting(**self.command(reaffirmed=True, clarification="Mara still fits."))
        self.assertEqual(decision.original_context["title"], "Quiet City")
        self.assertEqual(decision.reviewed_context["title"], "Renamed City")
        self.assertEqual(decision.clarification, "Mara still fits.")

    def test_archive_keeps_exact_original_context_and_sources(self):
        state = deepcopy(self.state)
        archive(state)
        self.assertEqual(state["history"][0]["context"], self.context)
        state["context"]["title"] = "Changed"
        self.assertEqual(state["history"][0]["context"]["title"], "Quiet City")
        state["attempt_id"] = str(uuid4())
        state["findings"] = None
        self.parent.request_payload = {"interpretation": state}
        self.parent.save()
        decide_sighting(**self.command())

    def test_keep_failure_rolls_back_decision(self):
        with patch("heddle.handoff.keep_sighting", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                decide_sighting(**self.command(disposition="defer"))
        self.assertFalse(FolioSightingDecision.objects.exists())
        self.assertFalse(ProvisionalData.objects.exists())

    def test_explicit_link_adds_context_without_learning_alias(self):
        decision = decide_sighting(**self.command(disposition="link_entity", new_entity_name="Mara Vale"))
        self.assertEqual(decision.entity.aliases, [])
        self.folio.refresh_from_db()
        self.assertEqual(self.folio.context_revision, 2)
        self.assertEqual(current_context(self.folio)["entities"][0]["name"], "Mara Vale")

    def test_failure_after_keep_rolls_back_provisional_row(self):
        with patch("folio.models.FolioSightingDecision.objects.create", side_effect=RuntimeError("insert failed")):
            with self.assertRaises(RuntimeError):
                decide_sighting(**self.command(disposition="defer"))
        self.assertFalse(ProvisionalData.objects.exists())

    def test_other_sponsors_entity_cannot_be_linked(self):
        from storyboard.models import Entity
        from django.contrib.contenttypes.models import ContentType
        entity = Entity.objects.create(name="Mara", kind="character", created_by=self.other,
            sponsor_content_type=ContentType.objects.get_for_model(self.other), sponsor_object_id=self.other.pk)
        with self.assertRaises(InterpretationError):
            decide_sighting(**self.command(disposition="link_entity", entity_id=entity.pk))
        self.assertFalse(FolioSightingDecision.objects.exists())

    def test_failed_attempt_is_not_a_decidable_finding(self):
        self.state["status"] = "failed"
        self.parent.request_payload = {"interpretation": self.state}
        self.parent.save()
        with self.assertRaises(InterpretationError):
            decide_sighting(**self.command())
