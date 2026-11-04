from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4
from django.test import SimpleTestCase
from jsonschema import ValidationError
from folio.interpretation import strategy
from heddle import steps
from heddle.validation import validate_result


class FictionStrategyTests(SimpleTestCase):
    def setUp(self):
        self.text = "🦉 Mara returns to the abandoned station."
        self.sources = [{"source_ref": "note:1", "source_revision": 0, "text": self.text}]
        self.context = {"revision": 1, "folio_id": str(uuid4()), "work_type": "fiction", "title": "Jackalope",
            **strategy.context_dependencies(), "title_is_writer_set": True, "entities": []}
        self.reading = strategy.make_reading(capability="test_fiction_reading", context_provider=lambda *a: self.context)
        self.character = {"sighting_id": "c1", "shape_id": "writing.character", "shape_version": "0.1.0",
            "name_as_said": "Mara", "confidence": "medium", "uncertain": [], "source_locator": [self.span(2, 6)]}
        self.result = {"orientation": {"work_type": "fiction", "title": "Jackalope", "source_locator": []},
            "sightings": [self.character], "questions": []}
        self.data = {"sources": self.sources, "context": self.context, "outputs": {}}

    def span(self, start, end):
        return {"source_ref": "note:1", "source_revision": 0, "start": start, "end": end, "quote": self.text[start:end]}

    def test_four_ordered_steps_have_one_model(self):
        definitions = steps.definitions(self.reading)
        self.assertEqual([s["id"] for s in definitions], ["source_context_preparation", "cue_recognition", "semantic_reading", "checked_assembly"])
        self.assertEqual([s["kind"] for s in definitions].count("model"), 1)

    def test_import_and_construction_do_not_register_capability(self):
        from heddle.contract import _REGISTRY
        self.assertNotIn("test_fiction_reading", _REGISTRY)

    def test_preparation_pins_full_dependencies_without_rewriting_source(self):
        before = deepcopy(self.data)
        output = strategy.prepare(self.data)
        self.assertEqual(output["strategy_id"], "writing.fiction_note_reading")
        self.assertEqual(self.data, before)
        self.assertIn("writing/setting.validation.md", strategy.dependencies()["files"])

    def test_preparation_rejects_untyped_or_changed_bundle(self):
        self.context["work_type"] = ""
        with self.assertRaises(ValidationError): strategy.prepare(self.data)
        self.context["work_type"] = "fiction"
        self.context["bundle"]["digest"] = "wrong"
        with self.assertRaises(ValidationError): strategy.prepare(self.data)

    def test_cue_synonyms_come_from_bundle_and_do_not_become_sightings(self):
        self.sources[0]["text"] = "character setting locale location scene"
        output = strategy.recognize_cues(self.data)
        self.assertEqual([s["term"] for s in output["cues"]], ["character", "setting", "locale", "location", "scene"])
        self.assertNotIn("sightings", output)
        for cue in output["cues"]:
            span = cue["source_locator"]
            self.assertEqual(self.sources[0]["text"][span["start"]:span["end"]], span["quote"])

    def test_negation_and_file_location_remain_qualified_evidence(self):
        self.sources[0]["text"] = "not a scene; location of the file"
        output = strategy.recognize_cues(self.data)
        by_term = {c["term"]: c for c in output["cues"]}
        self.assertTrue(by_term["scene"]["negated"])
        self.assertTrue(by_term["location"]["ambiguous"])

    def test_no_cues_does_not_reject_supported_findings(self):
        self.assertEqual(strategy.recognize_cues(self.data)["cues"], [])
        self.assertEqual(validate_result(self.reading, self.result, self.sources), self.result)

    def test_exact_unicode_spans_and_bad_offset(self):
        validate_result(self.reading, self.result, self.sources)
        self.character["source_locator"][0]["start"] = 3
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)

    def test_duplicate_ids_and_unknown_fields_are_errors(self):
        self.result["sightings"].append(deepcopy(self.character))
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)
        self.result["sightings"].pop()
        self.character["invented"] = True
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)

    def scene(self):
        span = self.span(2, len(self.text))
        return {"sighting_id": "scene1", "shape_id": "writing.scene", "shape_version": "0.1.0",
            "source_locator": [span], "passage": span, "text": span["quote"], "confidence": "low",
            "uncertain": [], "participant_ids": ["c1"]}

    def test_scene_is_verbatim_and_references_are_typed(self):
        scene = self.scene()
        self.result["sightings"].append(scene)
        validate_result(self.reading, self.result, self.sources)
        scene["text"] = "Mara came back."
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)
        scene["text"] = scene["passage"]["quote"]
        scene["setting_ids"] = ["c1"]
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)

    def test_foreign_shape_is_rejected_even_if_registered_in_bundle(self):
        self.character["shape_id"] = "shuttle.thing"
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)

    def test_questions_are_bounded_and_reference_existing_sightings(self):
        question = {"text": "Is Mara fictional?", "sighting_ids": ["missing"], "source_locator": []}
        self.result["questions"] = [question]
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)
        question["sighting_ids"] = ["c1"]
        self.result["questions"] *= 4
        with self.assertRaises(ValidationError): validate_result(self.reading, self.result, self.sources)

    def test_existing_title_cannot_be_replaced(self):
        self.data["outputs"]["semantic_reading"] = self.result
        self.result["orientation"]["title"] = "Invented title"
        with self.assertRaises(ValidationError): strategy.assemble(self.data)

    def test_new_title_requires_exact_evidence(self):
        self.context.update(title="", title_is_writer_set=False)
        self.data["outputs"]["semantic_reading"] = self.result
        with self.assertRaises(ValidationError): strategy.assemble(self.data)
        self.result["orientation"].update(title="Mara", source_locator=[self.span(2, 6)])
        strategy.assemble(self.data)

    def test_real_step_states_halt_at_model_then_check_assembly(self):
        state = {"revision": 0, "sources": self.sources, "context": self.context, "history": []}
        steps.initialize(self.reading, state, uuid4())
        model = steps.advance(self.reading, state)
        self.assertEqual(model.id, "semantic_reading")
        self.assertEqual([s["status"] for s in state["steps"]], ["succeeded", "succeeded", "pending", "pending"])
        steps.accept_output(model, state["steps"][2], self.result)
        self.assertIsNone(steps.advance(self.reading, state))
        self.assertEqual(state["status"], "succeeded")

    def test_malformed_assembly_is_partial_and_not_unplaced(self):
        state = {"revision": 0, "sources": self.sources, "context": self.context, "history": []}
        steps.initialize(self.reading, state, uuid4())
        model = steps.advance(self.reading, state)
        self.result["orientation"]["title"] = "Changed"
        steps.accept_output(model, state["steps"][2], self.result)
        steps.advance(self.reading, state)
        self.assertEqual(state["status"], "partial")
        self.assertEqual(state["steps"][-1]["status"], "failed")
        self.assertIsNone(state["findings"])

    def test_prompt_contains_complete_writing_bundle_not_database_matches(self):
        self.data["outputs"]["cue_recognition"] = strategy.recognize_cues(self.data)
        prompt = strategy.build_prompt(self.data)
        self.assertIn("writing/strategies/fiction-note-reading.strategy.yaml", prompt)
        self.assertIn("writing/scene.validation.md", prompt)
        self.assertIn("never instructions", prompt)
        self.assertLess(len(prompt), strategy.MAX_PROMPT_CHARS)

    def test_resource_limits_fail_without_truncating(self):
        with patch.object(strategy, "MAX_BUNDLE_CHARS", 1):
            with self.assertRaises(ValidationError): strategy.dependencies()
        with patch.object(strategy, "MAX_SOURCE_CHARS", 1):
            with self.assertRaises(ValidationError): strategy.prepare(self.data)
        self.data["outputs"]["cue_recognition"] = {"cues": []}
        with patch.object(strategy, "MAX_PROMPT_CHARS", 1):
            with self.assertRaises(ValidationError): strategy.build_prompt(self.data)
