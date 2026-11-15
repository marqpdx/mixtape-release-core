"""`folio_dictionary.nfc_casefold.v1` against Contour's rule. No database.

Non-ASCII test text is written as escapes on purpose, so an editor cannot
quietly recompose it.
"""
import subprocess
import sys
import unicodedata
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from folio.dictionary import matching

APP = Path(__file__).resolve().parents[2]


def entry(entry_id, main, *variants, revision=1):
    return {"entry_id": entry_id, "revision": revision, "names": {"main": main, "variants": list(variants)}}


def spans(text, *entries):
    return [(m["start"], m["end"], m["quote"]) for m in matching.find_matches(text, entries)]


class RuleTests(SimpleTestCase):
    def test_key_is_nfc_casefold_nfc_and_changes_nothing_stored(self):
        stored = "Cafe\u0301 STRASSE"
        self.assertEqual(matching.match_key(stored), "caf\xe9 strasse")
        self.assertEqual(stored, "Cafe\u0301 STRASSE")
        self.assertTrue(matching.equivalent("Stra\xdfe", "STRASSE"))
        self.assertTrue(matching.equivalent("Caf\xe9", "CAFE\u0301"))

    def test_no_accent_stripping_transliteration_or_compatibility_folding(self):
        self.assertFalse(matching.equivalent("Caf\xe9", "Cafe"))
        self.assertFalse(matching.equivalent("\uff2d\uff41\uff52\uff41", "Mara"))  # fullwidth
        self.assertFalse(matching.equivalent("M\xfcller", "Mueller"))

    def test_full_case_folding_does_fold_ligatures(self):
        # Part of Unicode full case folding, so part of the rule as written.
        self.assertTrue(matching.equivalent("\ufb01n", "FIN"))

    def test_turkish_dotted_and_dotless_i_are_not_plain_i(self):
        self.assertFalse(matching.equivalent("\u0130stanbul", "istanbul"))
        self.assertFalse(matching.equivalent("\u0131stanbul", "istanbul"))
        self.assertTrue(matching.equivalent("\u0130stanbul", "i\u0307stanbul"))

    def test_casefold_can_expose_a_new_composition(self):
        # Combining ypogegrammeni folds to a full iota: the reason for the outer NFC.
        self.assertTrue(matching.equivalent("\u03b1\u0345", "\u0391\u0399"))

    def test_identity_pins_rule_implementation_and_unicode_data(self):
        identity = matching.identity()
        self.assertEqual(identity["rule"], "folio_dictionary.nfc_casefold.v1")
        self.assertEqual(identity["unicode_version"], unicodedata.unidata_version)
        self.assertRegex(identity["implementation_sha256"], r"^[a-f0-9]{64}$")

    def test_importable_without_django(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from folio.dictionary import matching; "
                "assert 'django' not in sys.modules; print(matching.identity()['implementation_sha256'])")
        out = subprocess.run([sys.executable, "-I", "-c", code, str(APP)], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), matching.identity()["implementation_sha256"])


class SpanTests(SimpleTestCase):
    def test_offsets_are_original_code_points_past_a_non_bmp_character(self):
        self.assertEqual(spans("\U0001f989 Mara meets Lucy", entry("a", "mara")), [(2, 6, "Mara")])

    def test_decomposed_source_keeps_its_own_spelling_and_length(self):
        text = "At Cafe\u0301, then Caf\xe9."
        self.assertEqual(spans(text, entry("a", "CAF\xc9")), [(3, 8, "Cafe\u0301"), (15, 19, "Caf\xe9")])

    def test_case_fold_expansion_maps_back_to_the_original_span(self):
        text = "Die Stra\xdfe, die STRASSE."
        self.assertEqual(spans(text, entry("a", "strasse")), [(4, 10, "Stra\xdfe"), (16, 23, "STRASSE")])
        self.assertEqual(spans("STRASSE", entry("a", "Stra\xdfe")), [(0, 7, "STRASSE")])

    def test_never_matches_part_of_a_normalization_unit(self):
        self.assertEqual(spans("Stra\xdfe", entry("a", "Stras")), [])
        self.assertEqual(spans("Cafe\u0301", entry("a", "Cafe")), [])
        decomposed_han = "\u1112\u1161\u11ab"  # Hangul syllable U+D55C as three jamo
        self.assertEqual(spans(decomposed_han, entry("a", "\ud558")), [])  # no partial syllable
        self.assertEqual(spans(decomposed_han, entry("a", "\ud55c")), [(0, 3, decomposed_han)])

    def test_several_entries_on_one_span_stay_alternatives(self):
        found = matching.find_matches("Mara waits.", [entry("b", "mara", revision=4), entry("a", "Mara", "MARA", "Mara")])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["alternatives"], [
            {"entry_id": "a", "entry_revision": 1, "matched_names": ["Mara", "MARA"]},
            {"entry_id": "b", "entry_revision": 4, "matched_names": ["mara"]}])
        self.assertEqual(found[0]["rule"], matching.RULE)
        self.assertNotIn("score", found[0])

    def test_overlapping_names_are_all_reported_and_none_preferred(self):
        self.assertEqual(spans("Mary Ann left.", entry("a", "Mary"), entry("b", "Mary Ann"), entry("c", "Ann")),
                         [(0, 4, "Mary"), (0, 8, "Mary Ann"), (5, 8, "Ann")])

    def test_hit_inside_a_word_is_reported_and_marked(self):
        found = matching.find_matches("Anna met Ann.", [entry("a", "Ann")])
        self.assertEqual([(m["start"], m["word_bounded"]) for m in found], [(0, False), (9, True)])

    def test_spaces_in_a_stored_name_are_compared_as_stored(self):
        self.assertEqual(spans("Old  Town and Old Town", entry("a", "Old Town")), [(14, 22, "Old Town")])

    def test_empty_or_non_string_name_is_an_error(self):
        for bad in ("", None):
            with self.assertRaises(ValueError):
                matching.find_matches("Mara", [entry("a", bad)])

    def test_no_entries_and_empty_text(self):
        self.assertEqual(matching.find_matches("Mara", []), [])
        self.assertEqual(matching.find_matches("", [entry("a", "Mara")]), [])


class AlignmentTests(SimpleTestCase):
    def test_every_unit_start_still_starts_a_unit_after_folding(self):
        # Exhaustive over this interpreter's Unicode data: the property
        # that lets unit keys concatenate into the whole key.
        bad = [hex(cp) for cp in range(0x110000) if not 0xD800 <= cp <= 0xDFFF
               and matching._starts_unit(chr(cp)) and not matching._starts_unit(matching.match_key(chr(cp))[0])]
        self.assertEqual(bad, [])

    def test_text_opening_with_a_combining_mark_aligns(self):
        self.assertEqual(spans("\u0301Mara", entry("a", "mara")), [(1, 5, "Mara")])

    def test_misalignment_fails_instead_of_returning_evidence(self):
        with patch.object(matching, "_starts_unit", lambda ch: True):
            with self.assertRaises(matching.AlignmentError):
                matching.find_matches("e\u0301", [entry("a", "e")])
