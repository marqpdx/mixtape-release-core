from django.test import SimpleTestCase

from fundamentals.services.name_matching import MatchState, match_name

CHOIR_CHOIR_CHOIR = object()
PUB_CHOIR = object()
LOW_BAR_CHORALE = object()

EXISTING = [
    (CHOIR_CHOIR_CHOIR, "Choir! Choir! Choir!"),
    (PUB_CHOIR, "Pub Choir"),
    (LOW_BAR_CHORALE, "Low Bar Chorale"),
]


class MatchNameTests(SimpleTestCase):
    def test_exact_resubmission_is_a_clear_match(self):
        result = match_name(name="Choir! Choir! Choir!", candidates=EXISTING)

        self.assertEqual(result.state, MatchState.FOUND)
        self.assertIs(result.exact, CHOIR_CHOIR_CHOIR)

    def test_punctuation_only_difference_is_a_near_duplicate_not_exact(self):
        """The ADR's own example: identical once punctuation is stripped,
        but not light-exact, so it must be raised, not silently matched."""
        result = match_name(name="Choir Choir Choir", candidates=EXISTING)

        self.assertEqual(result.state, MatchState.NEAR_DUPLICATE)
        self.assertEqual(len(result.candidates), 1)
        self.assertIs(result.candidates[0].object, CHOIR_CHOIR_CHOIR)
        self.assertEqual(result.candidates[0].score, 100.0)

    def test_clear_non_match_is_new(self):
        result = match_name(name="Community Drum Circle", candidates=EXISTING)

        self.assertEqual(result.state, MatchState.NEW)
        self.assertEqual(result.candidates, [])

    def test_empty_name_is_new(self):
        result = match_name(name="   ", candidates=EXISTING)

        self.assertEqual(result.state, MatchState.NEW)

    def test_ambiguous_exact_matches_are_raised_not_silently_picked(self):
        duplicate_entry = object()
        candidates = EXISTING + [(duplicate_entry, "Choir! Choir! Choir!")]

        result = match_name(name="Choir! Choir! Choir!", candidates=candidates)

        self.assertEqual(result.state, MatchState.NEAR_DUPLICATE)
        self.assertEqual({c.object for c in result.candidates}, {CHOIR_CHOIR_CHOIR, duplicate_entry})
