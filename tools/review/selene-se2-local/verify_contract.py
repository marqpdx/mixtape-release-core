"""Offline review rehearsal, not imported by any production service.

Run with Core's existing environment. No database, model, network or Django
settings are needed. Schema and meaning checks are deliberately separate.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import unittest
from uuid import UUID

from jsonschema import Draft7Validator, FormatChecker, ValidationError

ROOT = Path(__file__).parent


def load(name):
    return json.loads((ROOT / name).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


CHECKER = FormatChecker()


@CHECKER.checks("uuid", raises=(ValueError, TypeError, AttributeError))
def uuid_format(value):
    return isinstance(value, str) and str(UUID(value)) == value


PROFILE = load("profile.json")
REQUEST = load("request.example.json")
RESPONSE = load("response.example.json")
SCHEMAS = {kind: load(kind + ".schema.json") for kind in ("request", "response")}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def schema(kind, value):
    Draft7Validator(SCHEMAS[kind], format_checker=CHECKER).validate(value)


def validate_request(request):
    schema("request", request)
    binding, sources, context = request["binding"], request["sources"], request["context"]
    require(request["profile_digest"] == digest(PROFILE), "profile_conflict")
    require(all(type(binding[k]) is int for k in ("revision", "context_revision")), "invalid_revision")
    require(type(context["revision"]) is int, "invalid_revision")
    require(binding["source_digest"] == digest(sources), "source_conflict")
    require(binding["context_digest"] == digest(context), "context_conflict")
    require(binding["context_revision"] == context["revision"], "context_conflict")
    require(binding["bundle_digest"] == context["bundle"]["digest"], "bundle_conflict")
    require(sum(len(s["text"]) for s in sources) <= PROFILE["max_source_chars"], "source_too_long")
    require(all(type(s["source_revision"]) is int and s["source_revision"] <= binding["revision"]
        and s["text"].strip() for s in sources), "invalid_source")
    require(len({(s["source_ref"], s["source_revision"]) for s in sources}) == len(sources), "duplicate_source")
    require(len(json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False)) <= PROFILE["max_context_chars"], "context_too_large")
    require(len(json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()) <= PROFILE["max_request_bytes"], "request_too_large")
    # Also rejects non-finite values in the opaque context; JSON NaN is not JSON.
    digest(request)


def validate_response(request, response):
    validate_request(request)
    schema("response", response)
    require(response["binding"] == request["binding"], "binding_conflict")
    require(response["profile_digest"] == request["profile_digest"], "profile_conflict")
    require(response["request_fingerprint"] == digest(request), "request_conflict")
    sources = {(s["source_ref"], s["source_revision"]): s["text"] for s in request["sources"]}
    ids, occurrences = set(), set()
    for candidate in response["candidates"]:
        locator = candidate["source_locator"]
        text = sources.get((locator["source_ref"], locator["source_revision"]))
        start, end = locator["start"], locator["end"]
        require(type(start) is int and type(end) is int and type(locator["source_revision"]) is int,
            "invalid_span")
        require(text is not None and 0 <= start < end <= len(text) and text[start:end] == locator["quote"],
            "invalid_span")
        score = candidate["score"]
        require(type(score) in (int, float) and math.isfinite(score), "invalid_score")
        key = {"execution_action_run_id": request["binding"]["execution_action_run_id"],
            "type": candidate["type"], "source_locator": locator}
        expected_id = "m-" + digest(key)[:32]
        require(candidate["candidate_id"] == expected_id, "candidate_identity_conflict")
        occurrence = (candidate["type"], locator["source_ref"], locator["source_revision"], start, end)
        require(expected_id not in ids and occurrence not in occurrences, "duplicate_candidate")
        ids.add(expected_id)
        occurrences.add(occurrence)
    require(len(json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()) <= PROFILE["max_response_bytes"], "response_too_large")
    digest(response)


class ContractReviewTests(unittest.TestCase):
    def invalid_request(self, change):
        request = copy.deepcopy(REQUEST)
        change(request)
        with self.assertRaises((ValidationError, ValueError, TypeError)):
            validate_request(request)

    def invalid_response(self, change):
        response = copy.deepcopy(RESPONSE)
        change(response)
        with self.assertRaises((ValidationError, ValueError, TypeError)):
            validate_response(REQUEST, response)

    def test_schemas_are_valid_draft_seven(self):
        for value in SCHEMAS.values():
            Draft7Validator.check_schema(value)

    def test_valid_unicode_and_multisource_examples(self):
        validate_response(REQUEST, RESPONSE)
        self.assertEqual(RESPONSE["candidates"][0]["source_locator"]["start"], 2)
        self.assertEqual(RESPONSE["candidates"][1]["source_locator"]["quote"], "Cafe\u0301")
        self.assertEqual(RESPONSE["candidates"][2]["source_locator"]["quote"], "Paris")

    def test_empty_real_model_result_can_be_valid(self):
        response = {**RESPONSE, "candidates": []}
        validate_response(REQUEST, response)
        # This validates wire shape only, never proves an execution happened.

    def test_unknown_request_field(self):
        self.invalid_request(lambda r: r.update(cloud_mode=True))

    def test_unknown_response_field(self):
        self.invalid_response(lambda r: r.update(sightings=[]))

    def test_cloud_request_forbidden(self):
        self.invalid_request(lambda r: r.update(local_only=False))

    def test_profile_not_caller_selected(self):
        self.invalid_request(lambda r: r.update(profile_digest="0" * 64))

    def test_source_text_requires_original_digest(self):
        self.invalid_request(lambda r: r["sources"][0].update(text="changed"))

    def test_context_text_requires_original_digest(self):
        self.invalid_request(lambda r: r["context"].update(title="changed"))

    def test_context_revision_must_agree(self):
        def change(r):
            r["context"]["revision"] += 1
            r["binding"]["context_digest"] = digest(r["context"])
        self.invalid_request(change)

    def test_bundle_must_agree(self):
        self.invalid_request(lambda r: r["binding"].update(bundle_digest="0" * 64))

    def test_revision_is_an_integer_not_boolean_or_float(self):
        for value in (True, 1.0):
            self.invalid_request(lambda r: r["binding"].update(revision=value))

    def test_aggregate_source_budget_refuses_without_truncation(self):
        def change(r):
            for s in r["sources"]:
                s["text"] = "x" * 3000
            r["binding"]["source_digest"] = digest(r["sources"])
        self.invalid_request(change)

    def test_duplicate_sources_refused(self):
        def change(r):
            r["sources"].append(r["sources"][0])
            r["binding"]["source_digest"] = digest(r["sources"])
        self.invalid_request(change)

    def test_blank_and_future_revision_sources_refused(self):
        for change in (lambda s: s.update(text=" "), lambda s: s.update(source_revision=2)):
            def mutate(r):
                change(r["sources"][0])
                r["binding"]["source_digest"] = digest(r["sources"])
            self.invalid_request(mutate)

    def test_invalid_uuid_is_not_just_a_format_annotation(self):
        self.invalid_request(lambda r: r["binding"].update(execution_action_run_id="not-a-uuid"))

    def test_every_binding_field_is_echoed_and_compared(self):
        for key, value in REQUEST["binding"].items():
            replacement = value + 1 if type(value) is int else "0" * len(value)
            self.invalid_response(lambda r: r["binding"].update({key: replacement}))

    def test_request_fingerprint_required(self):
        self.invalid_response(lambda r: r.update(request_fingerprint="0" * 64))

    def test_old_model_revision_refused(self):
        self.invalid_response(lambda r: r["candidates"][0]["producer"].update(model_revision="0" * 40))

    def test_wrong_profile_on_producer_refused(self):
        self.invalid_response(lambda r: r["candidates"][0]["producer"].update(profile_digest="0" * 64))

    def test_wrong_label_and_scene_not_repaired(self):
        for kind in ("person", "writing.scene"):
            self.invalid_response(lambda r: r["candidates"][0].update(type=kind))

    def test_canonical_sighting_fields_refused(self):
        for key, value in (("confidence", "high"), ("sighting_id", "s1"), ("status", "confirmed"), ("payload", {})):
            self.invalid_response(lambda r: r["candidates"][0].update({key: value}))

    def test_model_cannot_report_rule_or_human_origin(self):
        self.invalid_response(lambda r: r["candidates"][0].update(candidate_kind="cue"))
        self.invalid_response(lambda r: r["candidates"][0]["producer"].update(kind="person"))

    def test_nonfinite_boolean_null_and_out_of_range_scores(self):
        for value in (float("nan"), float("inf"), True, None, -0.1, 1.1):
            self.invalid_response(lambda r: r["candidates"][0].update(score=value))

    def test_scores_are_not_rounded_or_bucketed(self):
        validate_response(REQUEST, RESPONSE)
        self.assertEqual(RESPONSE["candidates"][0]["score"], 0.713)

    def test_wrong_span_quote_offset_revision_and_source(self):
        for fields in ({"start": 3}, {"quote": "MARA"}, {"end": 4001}, {"source_revision": 5},
                       {"source_ref": "another-folio"}, {"start": 2.0}, {"end": 2}):
            self.invalid_response(lambda r: r["candidates"][0]["source_locator"].update(fields))

    def test_normalized_quote_never_replaces_original(self):
        self.invalid_response(lambda r: r["candidates"][1]["source_locator"].update(quote="Caf\u00e9"))

    def test_candidate_identity_is_bound_to_real_child_reference(self):
        self.invalid_response(lambda r: r["candidates"][0].update(candidate_id="m-" + "0" * 32))

    def test_duplicate_predictions_fail_instead_of_silent_deduplication(self):
        self.invalid_response(lambda r: r["candidates"].append(r["candidates"][0]))

    def test_output_budget_fails_instead_of_silent_drop(self):
        self.invalid_response(lambda r: r.update(candidates=r["candidates"] * 100))

    def test_context_budget_is_explicit(self):
        def change(r):
            r["context"]["title"] = "x" * 40000
            r["binding"]["context_digest"] = digest(r["context"])
        self.invalid_request(change)

    def test_serialized_response_budget_is_explicit(self):
        # Keep candidate count within its own limit; overflow the byte budget.
        request = copy.deepcopy(REQUEST)
        request["sources"] = [{"source_ref": "note", "source_revision": 0, "text": "x" * 4000}]
        request["binding"]["source_digest"] = digest(request["sources"])
        response = copy.deepcopy(RESPONSE)
        response.update(binding=request["binding"], request_fingerprint=digest(request), candidates=[])
        for index in range(60):
            candidate = copy.deepcopy(RESPONSE["candidates"][0])
            locator = {"source_ref": "note", "source_revision": 0, "start": index, "end": 4000,
                "quote": "x" * (4000 - index)}
            candidate["source_locator"] = locator
            candidate["candidate_id"] = "m-" + digest({
                "execution_action_run_id": request["binding"]["execution_action_run_id"],
                "type": candidate["type"], "source_locator": locator})[:32]
            response["candidates"].append(candidate)
        with self.assertRaisesRegex(ValueError, "response_too_large"):
            validate_response(request, response)

    def test_context_is_opaque_but_cannot_hide_non_json_values(self):
        def change(r):
            r["context"]["unexpected_nonfinite_value"] = float("nan")
        self.invalid_request(change)


if __name__ == "__main__":
    unittest.main(verbosity=2)
