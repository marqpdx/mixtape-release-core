# almanac/tests/test_serializers.py

from django.utils import timezone
from django.test import TestCase

from almanac.api.serializers import EventCreateSerializer


class EventCreateSerializerTests(TestCase):
    def test_single_requires_start_end(self):
        serializer = EventCreateSerializer(
            data={
                "event_type": "single",
                "title": "Missing Times",
            }
        )
        self.assertFalse(serializer.is_valid())

    def test_single_rejects_end_before_start(self):
        serializer = EventCreateSerializer(
            data={
                "event_type": "single",
                "title": "Invalid Times",
                "start_time": timezone.now(),
                "end_time": timezone.now() - timezone.timedelta(hours=1),
            }
        )
        self.assertFalse(serializer.is_valid())

    def test_recurring_requires_rrule_and_duration(self):
        serializer = EventCreateSerializer(
            data={
                "event_type": "recurring",
                "title": "Missing RRULE",
                "start_time": timezone.now(),
                "end_time": timezone.now() + timezone.timedelta(hours=1),
            }
        )
        self.assertFalse(serializer.is_valid())
