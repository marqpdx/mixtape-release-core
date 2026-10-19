from django.contrib.auth import get_user_model
from django.test import TestCase

from writing.models import Seed, SeedDispatch
from writing.services import DispatchError, create_dispatch

User = get_user_model()


class CreateDispatchTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="dispatch-author",
            email="dispatch-author@example.com",
            password="testpass123",
        )
        self.seed = Seed.objects.create(author=self.author, body_text="Worth remembering")

    def test_commons_dispatch_needs_no_destination_id(self):
        dispatch = create_dispatch(seed=self.seed, destination_type="commons", verb="copy")
        self.assertIsNone(dispatch.destination_id)
        self.assertEqual(dispatch.outcome, "delivered")
        self.assertEqual(dispatch.seed_id, self.seed.id)

    def test_message_dispatch_requires_destination_id(self):
        with self.assertRaises(DispatchError):
            create_dispatch(seed=self.seed, destination_type="message", verb="copy")

    def test_message_dispatch_with_destination_id_succeeds(self):
        recipient_id = self.author.id
        dispatch = create_dispatch(
            seed=self.seed,
            destination_type="message",
            destination_id=recipient_id,
            verb="move",
        )
        self.assertEqual(dispatch.destination_id, recipient_id)
        self.assertEqual(dispatch.verb, "move")

    def test_unknown_destination_type_rejected(self):
        with self.assertRaises(DispatchError):
            create_dispatch(seed=self.seed, destination_type="carrier_pigeon")

    def test_multiple_dispatches_recorded_for_same_seed(self):
        create_dispatch(seed=self.seed, destination_type="commons")
        create_dispatch(seed=self.seed, destination_type="storyline", destination_id=self.author.id)
        self.assertEqual(SeedDispatch.objects.filter(seed=self.seed).count(), 2)
