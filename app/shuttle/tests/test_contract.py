import json
from pathlib import Path

from django.test import SimpleTestCase
from jsonschema import Draft7Validator

CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"
SCHEMA_DIR = CONTRACT_DIR / "schema"
FIXTURES_DIR = CONTRACT_DIR / "fixtures"


def load_json(path):
    with open(path) as f:
        return json.load(f)


class ShuttleContractFixturesValidateAgainstSchemaTests(SimpleTestCase):
    """SH-7a: the packet contract. Each fixture must validate against its schema (ADR-0058, Appendix A)."""

    def _assert_valid(self, schema_name, fixture_name):
        schema = load_json(SCHEMA_DIR / schema_name)
        instance = load_json(FIXTURES_DIR / fixture_name)
        validator = Draft7Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
        self.assertEqual(
            errors,
            [],
            msg="\n".join(f"{list(e.path)}: {e.message}" for e in errors),
        )

    def test_weave_in_fixture_validates(self):
        self._assert_valid("weave_in.schema.json", "three_choirs_weave_in.json")

    def test_packet_out_fixture_validates(self):
        self._assert_valid("packet_out.schema.json", "three_choirs_packet_out.json")

    def test_confirm_in_fixture_validates(self):
        self._assert_valid("confirm_in.schema.json", "three_choirs_confirm_in.json")

    def test_result_out_fixture_validates(self):
        self._assert_valid("result_out.schema.json", "three_choirs_result_out.json")

    def test_packet_out_marks_choir_choir_choir_as_found(self):
        packet = load_json(FIXTURES_DIR / "three_choirs_packet_out.json")
        item = next(i for i in packet["items"] if i["item_id"] == "thing-choir-choir-choir")
        self.assertEqual(item["match_state"], "found")

    def test_packet_out_has_exactly_one_near_duplicate(self):
        packet = load_json(FIXTURES_DIR / "three_choirs_packet_out.json")
        near_dupes = [i for i in packet["items"] if i["match_state"] == "near_duplicate"]
        self.assertEqual(len(near_dupes), 1)
        self.assertIn("candidate", near_dupes[0])

    def test_result_out_rests_unticked_place_and_thing_as_seed(self):
        confirm = load_json(FIXTURES_DIR / "three_choirs_confirm_in.json")
        result = load_json(FIXTURES_DIR / "three_choirs_result_out.json")
        self.assertNotIn("place-portland", confirm["ticked_item_ids"])
        self.assertNotIn("thing-low-bar-chorale", confirm["ticked_item_ids"])
        self.assertIn("place-portland", result["rested_as_seed"])
        self.assertIn("thing-low-bar-chorale", result["rested_as_seed"])

    def test_near_duplicate_candidate_requires_a_merge_answer_shape(self):
        """Not a server-side check (there is no server yet) — just that the fixture's
        merge_answers entry references the same candidate_id the packet surfaced."""
        packet = load_json(FIXTURES_DIR / "three_choirs_packet_out.json")
        confirm = load_json(FIXTURES_DIR / "three_choirs_confirm_in.json")
        near_dupe = next(i for i in packet["items"] if i["match_state"] == "near_duplicate")
        merge_answer = next(
            m for m in confirm["merge_answers"] if m["item_id"] == near_dupe["item_id"]
        )
        self.assertEqual(merge_answer["candidate_id"], near_dupe["candidate"]["id"])
