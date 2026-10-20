from django.contrib.auth import get_user_model
from django.test import TestCase

from classifications.models import Tag
from shuttle.models import IdeaTuple


class IdeaTupleTests(TestCase):
    """SH-9: the Idea-tuple holder for Stories Not Yet Told (D8)."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(
            username="weaver", email="weaver@example.com", password="x"
        )
        self.idea_karaoke = Tag.objects.create(title="Karaoke", slug="karaoke", is_idea=True)
        self.idea_singing = Tag.objects.create(title="Singing together", slug="singing-together", is_idea=True)

    def test_create_idea_tuple_with_facets(self):
        tuple_ = IdeaTuple.objects.create(
            label="Karaoke bars with a house choir night",
            source_offer_id="snt-karaoke-bars",
            author=self.author,
        )
        tuple_.ideas.set([self.idea_karaoke, self.idea_singing])

        self.assertEqual(set(tuple_.ideas.all()), {self.idea_karaoke, self.idea_singing})

    def test_search_by_one_idea_returns_the_tuple(self):
        tuple_ = IdeaTuple.objects.create(
            label="Karaoke bars with a house choir night",
            source_offer_id="snt-karaoke-bars",
            author=self.author,
        )
        tuple_.ideas.set([self.idea_karaoke])

        self.assertIn(tuple_, IdeaTuple.objects.filter(ideas=self.idea_karaoke))

    def test_action_run_is_optional_and_nullable_on_delete(self):
        tuple_ = IdeaTuple.objects.create(
            label="Busking choirs in transit stations",
            source_offer_id="snt-busking-choirs",
            author=self.author,
        )
        self.assertIsNone(tuple_.action_run)
