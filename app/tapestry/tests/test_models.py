from django.db import IntegrityError
from django.test import TestCase

from tapestry.models import Location, Place


class LocationPlaceSplitTests(TestCase):
    """Shuttle ADR-0058, OQ5 (2026-10-18): Location outlives its Places."""

    def test_one_location_hosts_many_places(self):
        location = Location.objects.create(
            address="123 Main St", latitude=45.5, longitude=-122.6,
        )
        taco_cart = Place.objects.create(name="Taco Cart", location=location)
        noodle_cart = Place.objects.create(name="Noodle Cart", location=location)

        self.assertEqual(set(location.places.all()), {taco_cart, noodle_cart})

    def test_place_requires_a_location(self):
        with self.assertRaises(IntegrityError):
            Place.objects.create(name="No Location Here", location=None)

    def test_location_cannot_be_deleted_while_places_reference_it(self):
        location = Location.objects.create(address="123 Main St")
        Place.objects.create(name="Taco Cart", location=location)

        with self.assertRaises(IntegrityError):
            location.delete()
