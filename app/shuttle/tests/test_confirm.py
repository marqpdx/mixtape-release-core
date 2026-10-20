from django.contrib.auth import get_user_model
from django.test import TestCase

from classifications.models import Tag
from commons.models import CommonsItem, LeafEntry
from commons.services import capture_item
from initiatives.models import ActionRun, ActionRunStatus
from relations.models import Relationship
from shuttle.confirm import confirm_weave
from shuttle.models import IdeaTuple
from shuttle.services import ShuttleEnvelopeError, hold_packet, start_weave
from tapestry.models import Location, Place
from writing.models import Seed


class ConfirmWeaveTests(TestCase):
    """SH-7b (b): the envelope's one-transaction confirm, against the
    three-choirs scenario (SH-7a's own fixture scenario, built from real
    rows here rather than replayed fixture ids)."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.other_author = get_user_model().objects.create_user(
            username="someone-else", email="someone-else@example.com", password="x"
        )

        # Pre-existing rows the packet's "found" and "near_duplicate" items
        # should resolve against, re-verified live rather than trusted.
        self.ccc = capture_item(self.author, title="Choir! Choir! Choir!")
        # Deliberately a title with no word overlap with "Choir! Choir!
        # Choir!" — RapidFuzz's WRatio scores "Pub Choir Collective" as a
        # 95 near-duplicate of it (shared "Choir" tokens), which would make
        # this fixture's own near-duplicate candidate collide with the
        # unrelated "found" thing it's meant to be tested alongside.
        self.pub_choir_collective = capture_item(self.author, title="Session Sing Brisbane")
        toronto_location = Location.objects.create(address="Toronto, ON")
        self.toronto = Place.objects.create(name="Toronto", location=toronto_location)

        self.weave_in = {
            "version": "1.0",
            "text": "Choir! Choir! Choir! and Pub Choir both do drop-in bar singalongs.",
            "client": "phone",
            "capture_mode": "typed",
        }

        self.packet = {
            "anchor": {
                "headline": "Packet: community singing",
                "counts": {"places": 3, "ideas": 2, "adjacencies": 3},
            },
            "items": [
                {"item_id": "place-toronto", "kind": "place", "name": "Toronto", "locale": "Toronto, ON", "match_state": "found"},
                {"item_id": "place-brisbane", "kind": "place", "name": "Brisbane", "locale": "Brisbane, QLD", "match_state": "new"},
                {"item_id": "place-portland", "kind": "place", "name": "Portland", "locale": "Portland, OR", "match_state": "new"},
                {"item_id": "thing-ccc", "kind": "thing", "name": "Choir! Choir! Choir!", "locale": "Toronto, ON", "match_state": "found"},
                {
                    "item_id": "thing-pub-choir",
                    "kind": "thing",
                    "name": "Pub Choir",
                    "locale": "Brisbane, QLD",
                    "match_state": "near_duplicate",
                    "candidate": {"id": str(self.pub_choir_collective.id), "name": "Pub Choir Collective", "score": 0.86},
                },
                {"item_id": "thing-low-bar-chorale", "kind": "thing", "name": "Low Bar Chorale", "locale": "Portland, OR", "match_state": "new"},
            ],
            "ideas": [
                {"idea_id": "idea-singing-together", "wording": "Singing together", "closest_existing": []},
                {"idea_id": "idea-gathering", "wording": "Gathering", "closest_existing": []},
            ],
            "adjacencies": [
                {"adjacency_id": "adj-ccc-pub", "ends": ["thing-ccc", "thing-pub-choir"], "reason": "Same practice."},
                {"adjacency_id": "adj-pub-lowbar", "ends": ["thing-pub-choir", "thing-low-bar-chorale"], "reason": "Same practice."},
                {"adjacency_id": "adj-ccc-lowbar", "ends": ["thing-ccc", "thing-low-bar-chorale"], "reason": "Same practice."},
            ],
            "story_prompts": [
                {"item_id": "place-toronto", "prompt": "What happened?"},
                {"item_id": "place-brisbane", "prompt": "What happened?"},
                {"item_id": "place-portland", "prompt": "What happened?"},
            ],
            "stories_not_yet_told": {
                "question": "Also note these for later?",
                "offers": [
                    {"id": "snt-karaoke-bars", "label": "Karaoke bars with a house choir night"},
                    {"id": "snt-busking-choirs", "label": "Busking choirs in transit stations"},
                ],
            },
        }

        action_run = start_weave(weave_in=self.weave_in, author=self.author)
        self.action_run_id = str(action_run.id)
        hold_packet(action_run_id=self.action_run_id, packet=self.packet, author=self.author)

        self.confirm_in = {
            "version": "1.0",
            "action_run_id": self.action_run_id,
            "ticked_item_ids": [
                "place-toronto", "place-brisbane",
                "thing-ccc", "thing-pub-choir",
                "idea-singing-together", "idea-gathering",
                "adj-ccc-pub",
            ],
            "stories": [
                {"item_id": "place-toronto", "text": "Packed into the back room on a Tuesday.", "music_link": "https://open.spotify.com/track/5eN7j3gHCmGIu2OKzSpbdU"},
                {"item_id": "place-brisbane", "text": "The bartender stopped pouring to sing the bass line."},
            ],
            "merge_answers": [
                {"item_id": "thing-pub-choir", "candidate_id": str(self.pub_choir_collective.id), "decision": "keep_separate"},
            ],
            "stories_not_yet_told_answer": True,
            "idea_rewordings": [],
        }

    def test_confirm_succeeds_the_action_run(self):
        confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        action_run = ActionRun.objects.get(pk=self.action_run_id)
        self.assertEqual(action_run.status, ActionRunStatus.SUCCEEDED)
        self.assertIsNotNone(action_run.completed_at)

    def _written_rows(self, result, item_id):
        return [w for w in result["written"] if w["item_id"] == item_id]

    def test_found_place_reuses_the_existing_row(self):
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        place_row = next(w for w in self._written_rows(result, "place-toronto") if w["written_as"] == "tapestry.Place")
        self.assertEqual(place_row["id"], str(self.toronto.id))

    def test_found_place_does_not_create_a_second_place(self):
        before = Place.objects.count()
        confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        self.assertEqual(Place.objects.count(), before + 1)  # +1 for brisbane (new); toronto reused

    def test_found_thing_reuses_the_existing_row(self):
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        ccc_row = next(w for w in self._written_rows(result, "thing-ccc") if w["written_as"] == "commons.CommonsItem")
        self.assertEqual(ccc_row["id"], str(self.ccc.id))

    def test_near_duplicate_keep_separate_creates_a_new_commons_item(self):
        before = CommonsItem.objects.count()
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        pub_row = next(w for w in self._written_rows(result, "thing-pub-choir") if w["written_as"] == "commons.CommonsItem")
        self.assertNotEqual(pub_row["id"], str(self.pub_choir_collective.id))
        self.assertEqual(CommonsItem.objects.count(), before + 1)  # keep_separate: one new row, ccc reused

    def test_story_writes_a_leaf_entry_with_music_link(self):
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        written_as = [w["written_as"] for w in result["written"] if w["item_id"] == "place-toronto"]
        self.assertIn("commons.LeafEntry", written_as)
        entry_id = next(w["id"] for w in result["written"] if w["item_id"] == "place-toronto" and w["written_as"] == "commons.LeafEntry")
        entry = LeafEntry.objects.get(pk=entry_id)
        self.assertEqual(entry.music_provider, LeafEntry.MUSIC_PROVIDER_SPOTIFY)

    def test_ticked_ideas_are_written_as_tags(self):
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        idea_rows = [w for w in result["written"] if w["written_as"] == "classifications.Tag"]
        self.assertEqual(len(idea_rows), 2)
        self.assertTrue(Tag.objects.get(title="Singing together").is_idea)

    def test_ticked_adjacencies_written_as_relationships(self):
        before = Relationship.objects.count()
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        adjacency_rows = [w for w in result["written"] if w["written_as"] == "relations.Relationship"]
        self.assertEqual(len(adjacency_rows), 1)
        self.assertEqual(Relationship.objects.count(), before + 1)

    def test_stories_not_yet_told_answer_true_writes_idea_tuples(self):
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        tuple_rows = [w for w in result["written"] if w["written_as"] == "shuttle.IdeaTuple"]
        self.assertEqual(len(tuple_rows), 2)
        self.assertEqual(IdeaTuple.objects.count(), 2)

    def test_unticked_place_and_thing_rest_as_seed(self):
        before = Seed.objects.count()
        result = confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        self.assertIn("place-portland", result["rested_as_seed"])
        self.assertIn("thing-low-bar-chorale", result["rested_as_seed"])
        self.assertEqual(Seed.objects.count(), before + 2)

    def test_confirm_rejects_a_requester_who_is_not_the_initiator(self):
        with self.assertRaises(ShuttleEnvelopeError):
            confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.other_author)

    def test_confirm_cannot_run_twice(self):
        confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)
        with self.assertRaises(ShuttleEnvelopeError):
            confirm_weave(action_run_id=self.action_run_id, confirm_in=self.confirm_in, author=self.author)

    def test_adjacency_ticked_without_both_ends_raises_and_rolls_back(self):
        confirm_in = {**self.confirm_in, "ticked_item_ids": [
            "place-toronto", "place-brisbane", "thing-ccc",
            "idea-singing-together", "idea-gathering",
            "adj-ccc-pub",  # thing-pub-choir is NOT ticked, but this adjacency is
        ]}
        with self.assertRaises(ShuttleEnvelopeError):
            confirm_weave(action_run_id=self.action_run_id, confirm_in=confirm_in, author=self.author)

        action_run = ActionRun.objects.get(pk=self.action_run_id)
        self.assertEqual(action_run.status, ActionRunStatus.FAILED)
        self.assertEqual(Relationship.objects.count(), 0)
        # The transaction rolled back entirely, including the Tags that would
        # otherwise have been written before the adjacency check failed.
        self.assertEqual(Tag.objects.filter(is_idea=True).count(), 0)
