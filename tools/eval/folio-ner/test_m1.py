import copy
import json
from pathlib import Path
import tempfile
import unittest

from adapter import digest, load_context, make_request, recognize, response_identity, validate_response
from dataset import compile_cases, locate, read_jsonl
from evaluation import evaluate, summarize

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT.parents[2] / "app/heddle/contour_bundle.json"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = load_context(BUNDLE)

    def request(self, text="🌙 Character: Élodie."):
        return make_request({"source_ref": "test:1", "source_revision": 0, "text": text}, copy.deepcopy(self.context))

    def test_context_has_all_cues_and_four_distinct_vocabularies(self):
        terms = {cue for row in self.context["vocabulary"] for cue in row["cues"]}
        self.assertEqual(terms, {"character", "setting", "locale", "location", "scene"})
        self.assertEqual(self.context["confirmed_entity_aliases"], [])
        self.assertEqual(self.context["project_markers"], [])
        self.assertEqual(self.context["field_labels"], [])

    def test_identity_matches_heddle_hashing_without_runtime_import(self):
        request = self.request()
        self.assertEqual(request["source_digest"], digest([request["source"]]))
        self.assertEqual(request["context_digest"], digest(request["context"]))

    def test_rules_have_no_mentions_model_scores_or_sightings(self):
        request = self.request()
        result = recognize(request)
        validate_response(request, result)
        self.assertEqual(result["candidates"][0]["source_locator"]["start"], 2)
        self.assertTrue(all(c["candidate_kind"] == "cue" and c["score"] is None for c in result["candidates"]))
        self.assertNotIn("sightings", result)

    def test_candidate_cannot_claim_sighting_state_or_extra_payload(self):
        request = self.request()
        for key in ("status", "sighting_id", "payload", "confidence"):
            result = recognize(request)
            result["candidates"][0][key] = "invented"
            with self.assertRaises(ValueError): validate_response(request, result)

    def test_each_identity_axis_rejects_stale_response(self):
        request = self.request()
        for field in response_identity(request):
            result = recognize(request)
            result[field] = "changed"
            with self.assertRaises(ValueError): validate_response(request, result)

    def test_wrong_unicode_offset_quote_and_boolean_offset_fail(self):
        request = self.request()
        for change in ({"start": 3}, {"quote": "character"}, {"start": True}):
            result = recognize(request)
            result["candidates"][0]["source_locator"].update(change)
            with self.assertRaises(ValueError): validate_response(request, result)

    def test_duplicate_candidate_id_fails_but_duplicate_span_is_scored(self):
        request = self.request()
        result = recognize(request)
        result["candidates"].append(copy.deepcopy(result["candidates"][0]))
        with self.assertRaises(ValueError): validate_response(request, result)
        result["candidates"][1]["candidate_id"] = "duplicate-span-distinct-id"
        validate_response(request, result)

    def test_model_provenance_requires_revision_and_scores_are_not_probabilities(self):
        request = self.request()
        result = recognize(request)
        candidate = result["candidates"][0]
        candidate["producer"] = {"kind": "model", "id": "synthetic-test-adapter", "version": "1", "model_revision": None}
        with self.assertRaises(ValueError): validate_response(request, result)
        candidate["producer"]["model_revision"] = "test-fixture-only"
        for score in (True, float("nan"), float("inf"), -1, 2):
            candidate["score"] = score
            with self.assertRaises(ValueError): validate_response(request, result)
        candidate["score"] = 0.6
        validate_response(request, result)

    def test_tampered_bundle_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = json.loads(BUNDLE.read_text())
            bundle["files"]["writing/character.shape.yaml"]["text"] += "\nChanged\n"
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(bundle))
            with self.assertRaises(ValueError): load_context(path)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / "cases.source.json").read_text())
        cls.context = load_context(BUNDLE)
        cls.cases = compile_cases(cls.rows, cls.context)

    def test_twenty_one_cases_all_splits_exact_spans_and_review_status(self):
        self.assertEqual(len(self.cases), 21)
        self.assertEqual({c["split"] for c in self.cases}, {"tuning", "contrast", "paraphrase", "holdout"})
        for case in self.cases:
            self.assertIn(case["annotation_status"], {"approved_as_written", "amended_per_cto", "authored_to_cto_spec"})
            text = case["request"]["source"]["text"]
            for collection in ("cues", "mentions", "traps", "ambiguities"):
                for a in case["annotations"][collection]:
                    self.assertEqual(text[a["start"]:a["end"]], a["quote"])

    def test_repeated_quote_requires_explicit_occurrence(self):
        with self.assertRaises(ValueError): locate("Mara meets Mara", {"quote": "Mara"})
        self.assertEqual(locate("Mara meets Mara", {"quote": "Mara", "occurrence": 2})["start"], 11)

    def test_decomposed_text_is_never_normalized(self):
        case = next(c for c in self.cases if c["id"] == "decomposed-unicode")
        self.assertEqual(case["annotations"]["mentions"][0]["quote"], "E\u0301lodie")
        self.assertEqual(case["annotations"]["mentions"][0]["end"] - case["annotations"]["mentions"][0]["start"], 7)

    def test_compiled_output_reproducible(self):
        self.assertEqual(list(read_jsonl(ROOT / "cases.jsonl")), self.cases)

    def test_duplicate_cases_and_text_rejected(self):
        for change in ("id", "text"):
            rows = copy.deepcopy(self.rows)
            rows[1][change] = rows[0][change]
            with self.assertRaises(ValueError): compile_cases(rows, self.context)

    def test_missing_response_is_failure_not_empty_predictions(self):
        with self.assertRaises(ValueError): evaluate(self.cases, [], "contrast")

    def test_wrong_split_and_duplicate_response_rejected(self):
        contrast = [c for c in self.cases if c["split"] == "contrast"]
        outputs = [recognize(c["request"]) for c in contrast]
        with self.assertRaises(ValueError): evaluate(self.cases, outputs, "holdout")
        with self.assertRaises(ValueError): evaluate(self.cases, outputs + outputs[:1], "contrast")

    def test_bad_gold_span_is_rejected_even_if_annotation_digest_is_updated(self):
        cases = copy.deepcopy(self.cases)
        case = next(c for c in cases if c["id"] == "explicit-character")
        case["annotations"]["mentions"][0]["start"] += 1
        case["annotation_digest"] = digest(case["annotations"])
        outputs = [recognize(c["request"]) for c in cases if c["split"] == "tuning"]
        with self.assertRaises(ValueError): evaluate(cases, outputs, "tuning")

    def test_baseline_exposes_qualifier_limitations_instead_of_claiming_ner(self):
        outputs = [recognize(c["request"]) for c in self.cases if c["split"] == "contrast"]
        report = evaluate(self.cases, outputs, "contrast")
        self.assertGreater(len(report["qualifier_errors"]), 0)
        self.assertGreater(len(report["ordinary_use_false_positives"]), 0)
        self.assertEqual(report["mentions"]["micro"]["tp"], 0)

    def test_boundary_type_errors_and_duplicates_are_reported_separately(self):
        gold = [{"source_ref": "a", "source_revision": 0, "type": "writing.character", "start": 0, "end": 4}]
        type_error = [{**gold[0], "type": "writing.setting"}]
        boundary_error = [{**gold[0], "end": 3}]
        self.assertEqual(len(summarize(type_error, gold)["type_errors"]), 1)
        self.assertEqual(len(summarize(boundary_error, gold)["boundary_errors"]), 1)
        self.assertEqual(summarize(gold * 2, gold)["micro"]["fp"], 1)
        self.assertEqual(summarize([], [])["micro"]["precision"], None)
        different_revision = [{**gold[0], "source_revision": 1}]
        self.assertEqual(summarize(different_revision, gold)["micro"]["tp"], 0)



class ReviewAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = list(read_jsonl(ROOT / "cases.jsonl"))

    def test_optional_gold_neither_rewards_nor_penalizes_a_hit(self):
        required = {"source_ref": "a", "source_revision": 0, "type": "writing.character", "start": 0, "end": 4}
        optional = {**required, "start": 10, "end": 15}
        absent = summarize([required], [required], [optional])
        present = summarize([required, optional], [required], [optional])
        self.assertEqual(absent["micro"], present["micro"])
        self.assertEqual(absent["optional"]["hit_count"], 0)
        self.assertEqual(present["optional"]["hit_count"], 1)
        self.assertEqual(present["false_positives"], [])
        self.assertEqual(present["false_negatives"], [])

    def test_optional_duplicate_is_still_a_duplicate_and_wrong_type_is_not_ignored(self):
        optional = {"source_ref": "a", "source_revision": 0, "type": "writing.character", "start": 0, "end": 5}
        duplicate = summarize([optional, optional], [], [optional])
        self.assertEqual(duplicate["micro"]["fp"], 1)
        self.assertEqual(duplicate["optional"]["hit_count"], 1)
        wrong = summarize([{**optional, "type": "writing.setting"}], [], [optional])
        self.assertEqual(wrong["micro"]["fp"], 1)
        self.assertEqual(wrong["optional"]["hit_count"], 0)

    def test_dataset_optional_baker_flag_is_neutral_in_full_evaluation(self):
        case = copy.deepcopy(next(c for c in self.cases if c["id"] == "unconfirmed-alias"))
        baker = next(m for m in case["annotations"]["mentions"] if m["quote"] == "baker")
        self.assertIs(baker["optional"], True)
        request = case["request"]
        absent = recognize(request)
        present = copy.deepcopy(absent)
        present["candidates"].append({"candidate_id": "optional-baker", "candidate_kind": "mention", "type": baker["type"],
            "source_locator": {"source_ref": request["source"]["source_ref"], "source_revision": 0,
                               **{k: baker[k] for k in ("start", "end", "quote")}},
            "score": None, "negated": False, "ambiguous": True, "uncertain": ["tentative alias"],
            "producer": {"kind": "rule", "id": "unit-test-only", "version": "1", "model_revision": None}})
        before, after = evaluate([case], [absent], "tuning"), evaluate([case], [present], "tuning")
        self.assertEqual(before["mentions"]["micro"], after["mentions"]["micro"])
        self.assertEqual(after["mentions"]["optional"]["hit_count"], 1)

    def test_relaxed_overlap_is_supplemental_and_uses_one_to_one_matching(self):
        base = {"source_ref": "a", "source_revision": 0, "type": "writing.character"}
        gold = [{**base, "start": 0, "end": 4}, {**base, "start": 6, "end": 10}]
        predicted = [{**base, "start": 0, "end": 10}, gold[0]]
        report = summarize(predicted, gold)
        self.assertEqual(report["micro"]["tp"], 1)
        self.assertEqual(report["relaxed_overlap_micro"]["tp"], 2)
        duplicates = summarize([gold[0], gold[0]], [gold[0]])
        self.assertEqual(duplicates["relaxed_overlap_micro"]["fp"], 1)

    def test_articles_and_possessive_are_outside_mentions(self):
        for case in self.cases:
            for mention in case["annotations"]["mentions"]:
                self.assertFalse(mention["quote"].lower().startswith(("the ", "a ", "an ")))
        case = next(c for c in self.cases if c["id"] == "possessive-multiword")
        name = next(m for m in case["annotations"]["mentions"] if m["type"] == "writing.character")
        self.assertEqual(name["quote"], "Captain Ruiz")
        self.assertEqual(case["request"]["source"]["text"][name["end"]:name["end"]+2], "'s")

    def test_spoken_lengths_correction_and_holdout_split(self):
        long = next(c for c in self.cases if c["id"] == "spoken-self-correction")
        short = next(c for c in self.cases if c["id"] == "spoken-no-cues")
        self.assertTrue(600 <= len(long["request"]["source"]["text"]) <= 900)
        self.assertTrue(200 <= len(short["request"]["source"]["text"]) <= 300)
        self.assertEqual(long["split"], "holdout")
        self.assertIn("Mara — no, Mira", long["request"]["source"]["text"])
        self.assertEqual(long["annotations"]["cues"], [])
        self.assertEqual(short["annotations"]["cues"], [])

    def test_mixed_normalization_is_deliberate_and_retained(self):
        import unicodedata
        case = next(c for c in self.cases if c["id"] == "decomposed-unicode")
        names = {m["type"]: m["quote"] for m in case["annotations"]["mentions"]}
        self.assertFalse(unicodedata.is_normalized("NFC", names["writing.character"]))
        self.assertTrue(unicodedata.is_normalized("NFC", names["writing.setting"]))
        self.assertIn("Deliberate", case["notes"])

    def test_generic_train_stations_setting_false_positive_is_reported(self):
        case = copy.deepcopy(next(c for c in self.cases if c["id"] == "negated-scene"))
        trap = next(t for t in case["annotations"]["traps"] if t["quote"] == "train stations")
        request = case["request"]
        response = recognize(request)
        response["candidates"].append({"candidate_id": "train-trap", "candidate_kind": "mention", "type": "writing.setting",
            "source_locator": {"source_ref": request["source"]["source_ref"], "source_revision": 0,
                               **{k: trap[k] for k in ("start", "end", "quote")}},
            "score": None, "negated": False, "ambiguous": False, "uncertain": [],
            "producer": {"kind": "rule", "id": "unit-test-only", "version": "1", "model_revision": None}})
        report = evaluate([case], [response], "contrast")
        self.assertTrue(any(e["candidate"]["quote"] == "train stations" for e in report["ordinary_use_false_positives"]))


if __name__ == "__main__":
    unittest.main()
