from django.contrib.auth import get_user_model
from django.test import TestCase

from commons.leaf_services import LeafServiceError, add_entry, close_leaf, open_leaf
from commons.models import Leaf, LeafEntry
from tapestry.models import Location, Place

User = get_user_model()


class LeafServicesTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(
            username="leaf-author",
            email="leaf-author@example.com",
            password="testpass123",
        )
        location = Location.objects.create(address="123 Main St")
        self.place = Place.objects.create(name="The Mod Club", location=location)

    def test_open_leaf_starts_open_with_no_place(self):
        leaf = open_leaf(author=self.author)
        self.assertEqual(leaf.state, Leaf.STATE_OPEN)
        self.assertIsNone(leaf.place)

    def test_open_leaf_can_set_place_up_front(self):
        leaf = open_leaf(author=self.author, place=self.place)
        self.assertEqual(leaf.place_id, self.place.pk)

    def test_add_entry_orders_by_position(self):
        leaf = open_leaf(author=self.author)
        first = add_entry(leaf=leaf, kind=LeafEntry.KIND_TEXT, body_text="First")
        second = add_entry(leaf=leaf, kind=LeafEntry.KIND_TEXT, body_text="Second")
        self.assertEqual(first.position, 1)
        self.assertEqual(second.position, 2)

    def test_add_entry_rejects_closed_leaf(self):
        leaf = open_leaf(author=self.author, place=self.place)
        close_leaf(leaf=leaf, library_only=True)
        with self.assertRaises(LeafServiceError):
            add_entry(leaf=leaf, kind=LeafEntry.KIND_TEXT, body_text="Too late")

    def test_close_leaf_requires_place_when_shared(self):
        leaf = open_leaf(author=self.author)
        with self.assertRaises(LeafServiceError):
            close_leaf(leaf=leaf, library_only=False)

    def test_close_leaf_library_only_does_not_require_place(self):
        leaf = open_leaf(author=self.author)
        closed = close_leaf(leaf=leaf, library_only=True)
        self.assertEqual(closed.state, Leaf.STATE_CLOSED)
        self.assertTrue(closed.library_only)
        self.assertIsNone(closed.published_at)

    def test_close_leaf_shared_sets_published_at(self):
        leaf = open_leaf(author=self.author, place=self.place)
        closed = close_leaf(leaf=leaf, library_only=False)
        self.assertEqual(closed.state, Leaf.STATE_CLOSED)
        self.assertFalse(closed.library_only)
        self.assertIsNotNone(closed.published_at)

    def test_close_leaf_is_idempotent(self):
        leaf = open_leaf(author=self.author, place=self.place)
        first_close = close_leaf(leaf=leaf, library_only=False)
        published_at = first_close.published_at
        second_close = close_leaf(leaf=leaf, library_only=True)
        self.assertEqual(second_close.published_at, published_at)
        self.assertFalse(second_close.library_only)
