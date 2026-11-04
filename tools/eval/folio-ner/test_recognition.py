import copy
import unittest
from recognition import Request, cue_matcher, exact_span_scores, validate_result

# Synthetic caller context, not a second copy of Contour's Shape schemas.
ALIASES = (("writing.character", "character"), ("writing.setting", "setting"),
           ("writing.setting", "locale"), ("writing.setting", "location"), ("writing.scene", "scene"))


class RecognitionTests(unittest.TestCase):
    def request(self, text):
        return Request(text, 1, "synthetic-fiction-v1", ALIASES)

    def test_aliases_case_unicode_and_word_boundaries(self):
        request = self.request("🎙 Locale: station. LOCATION: harbor. Characteristic isn't a character. Scene.")
        result = cue_matcher(request)
        self.assertEqual([c["span"]["quote"] for c in result["cues"]], ["Locale", "LOCATION", "character", "Scene"])
        self.assertEqual(result["cues"][0]["span"]["start"], 2)
        self.assertTrue(result["cues"][2]["negated"])
        self.assertEqual(result["mentions"], [], "Cue matching must not invent Entity mentions")
        validate_result(request, result)

    def test_ordinary_word_use_is_visible_as_ambiguous(self):
        result = cue_matcher(self.request("The location of the file is private. Locale: station."))
        self.assertTrue(result["cues"][0]["ambiguous"])
        self.assertFalse(result["cues"][1]["ambiguous"])

    def test_context_change_invalidates_old_result(self):
        request = self.request("Character: Mara.")
        result = cue_matcher(request)
        changed = Request(request.text, 1, "synthetic-fiction-v2", ALIASES)
        with self.assertRaises(ValueError):
            validate_result(changed, result)

    def test_changed_vocabulary_invalidates_same_version_result(self):
        request = self.request("Locale: station.")
        changed = Request(request.text, 1, request.context_version, ALIASES[:-1])
        with self.assertRaises(ValueError):
            validate_result(changed, cue_matcher(request))

    def test_changed_source_revision_invalidates_result(self):
        request = self.request("Scene: return.")
        with self.assertRaises(ValueError):
            validate_result(Request(request.text, 2, request.context_version, ALIASES), cue_matcher(request))

    def test_rewritten_quote_and_utf16_offsets_are_rejected(self):
        request = self.request("🎙 Scene: return.")
        result = cue_matcher(request)
        bad = copy.deepcopy(result)
        bad["cues"][0]["span"]["start"] += 1
        with self.assertRaises(ValueError): validate_result(request, bad)
        result["cues"][0]["span"]["quote"] = "scene"
        with self.assertRaises(ValueError): validate_result(request, result)

    def test_duplicate_vocab_alias_does_not_inflate_candidate_count(self):
        request = Request("Locale", 1, "test", ALIASES + (("writing.setting", "LOCALE"),))
        self.assertEqual(len(cue_matcher(request)["cues"]), 1)

    def test_scoring_duplicates_types_and_partial_boundaries(self):
        gold = [{"label": "character", "start": 2, "end": 6}]
        self.assertEqual(exact_span_scores(gold * 2, gold)["fp"], 1)
        wrong = [{"label": "setting", "start": 2, "end": 6}]
        self.assertEqual(exact_span_scores(wrong, gold)["fn"], 1)
        partial = [{"label": "character", "start": 2, "end": 5}]
        self.assertEqual(exact_span_scores(partial, gold)["tp"], 0)
        self.assertEqual(exact_span_scores([], [])["precision"], None)
        first = [{**gold[0], "source_ref": "note-a"}]
        second = [{**gold[0], "source_ref": "note-b"}]
        self.assertEqual(exact_span_scores(first, second)["tp"], 0)


if __name__ == "__main__":
    unittest.main()
