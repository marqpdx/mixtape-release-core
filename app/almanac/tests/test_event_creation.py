"""
Event Creation Tests

Tests for creating different types of events:
- Single events
- Recurring events (RRULE)
- Adhoc series
- Gatherings
"""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from almanac.models import Event, EventSeries, EventOccurrence
from .fixtures import AlmanacTestMixin


class SingleEventCreationTestCase(AlmanacTestMixin, TestCase):
    """Tests for creating single (one-time) events"""

    def test_create_basic_single_event(self):
        """Test creating a simple single event"""
        event = self.create_test_event(
            title="Workshop on Testing",
            description="Learn to write tests"
        )

        self.assertEqual(event.title, "Workshop on Testing")
        self.assertEqual(event.description, "Learn to write tests")
        self.assertEqual(event.author, self.user1)
        self.assertEqual(event.sponsor, self.group)
        self.assertIsNotNone(event.series)
        self.assertFalse(event.is_recurring)

    def test_single_event_creates_series(self):
        """Test that single events automatically create an EventSeries"""
        event = self.create_test_event()

        self.assertIsNotNone(event.series)
        self.assertIsInstance(event.series, EventSeries)
        self.assertEqual(event.series.event, event)

    def test_single_event_creates_one_occurrence(self):
        """Test that single events create exactly one occurrence"""
        event = self.create_test_event()

        occurrences = EventOccurrence.objects.filter(series=event.series)
        self.assertEqual(occurrences.count(), 1)

        occurrence = occurrences.first()
        self.assertEqual(occurrence.start, event.series.next_occurrence.start)
        self.assertFalse(occurrence.is_cancelled)

    def test_event_with_max_attendees(self):
        """Test creating an event with max attendee limit"""
        event = self.create_test_event(
            title="Limited Workshop",
            max_attendees=10
        )

        self.assertEqual(event.max_attendees, 10)
        self.assertFalse(event.series.next_occurrence.is_full())

    def test_event_datetime_validation(self):
        """Test that end time must be after start time"""
        start_time = self.tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
        end_time = self.tomorrow.replace(hour=13, minute=0, second=0, microsecond=0)  # Before start

        with self.assertRaises(Exception):
            Event.objects.create_single_event(
                title="Invalid Event",
                sponsor=self.group,
                author=self.user1,
                start_time=start_time,
                end_time=end_time
            )

    def test_event_slug_generation(self):
        """Test that events automatically generate unique slugs"""
        event1 = self.create_test_event(title="Workshop on Testing")
        event2 = self.create_test_event(title="Workshop on Testing")

        self.assertNotEqual(event1.slug, event2.slug)
        self.assertTrue(event1.slug.startswith("workshop-on-testing"))


class RecurringEventCreationTestCase(AlmanacTestMixin, TestCase):
    """Tests for creating recurring events with RRULE"""

    def test_create_weekly_recurring_event(self):
        """Test creating a weekly recurring event"""
        event = self.create_recurring_event(
            title="Weekly Standup",
            rrule='FREQ=WEEKLY;COUNT=4'
        )

        self.assertEqual(event.title, "Weekly Standup")
        self.assertTrue(event.is_recurring)
        self.assertIsNotNone(event.series)
        self.assertEqual(event.series.rrule, 'FREQ=WEEKLY;COUNT=4')

    def test_recurring_event_creates_first_occurrence(self):
        """Test that recurring events create at least the first occurrence"""
        event = self.create_recurring_event(
            rrule='FREQ=DAILY;COUNT=5'
        )

        occurrences = EventOccurrence.objects.filter(series=event.series)
        self.assertGreaterEqual(occurrences.count(), 1)

        first_occurrence = occurrences.order_by('start').first()
        self.assertIsNotNone(first_occurrence)

    def test_recurring_event_with_until_date(self):
        """Test recurring event with UNTIL clause"""
        until_date = self.tomorrow + timedelta(days=30)
        until_str = until_date.strftime('%Y%m%d')

        event = self.create_recurring_event(
            title="Daily Meditation",
            rrule=f'FREQ=DAILY;UNTIL={until_str}'
        )

        self.assertIn('UNTIL', event.series.rrule)
        self.assertTrue(event.is_recurring)

    def test_recurring_event_stores_timezone(self):
        """Test that recurring events store timezone information"""
        event = self.create_recurring_event(
            timezone='America/New_York'
        )

        self.assertEqual(event.series.timezone, 'America/New_York')

    def test_recurring_event_stores_duration(self):
        """Test that recurring events store default duration"""
        event = self.create_recurring_event(
            default_duration_minutes=90
        )

        self.assertEqual(event.series.default_duration_minutes, 90)


class AdhocSeriesCreationTestCase(AlmanacTestMixin, TestCase):
    """Tests for creating adhoc series (custom date events)"""

    def test_create_adhoc_series(self):
        """Test creating an adhoc series with custom dates"""
        event = self.create_adhoc_series(num_slots=3)

        self.assertIsNotNone(event.series)
        occurrences = EventOccurrence.objects.filter(series=event.series)
        self.assertEqual(occurrences.count(), 3)

    def test_adhoc_series_preserves_slot_order(self):
        """Test that adhoc series occurrences are in correct order"""
        event = self.create_adhoc_series(num_slots=5)

        occurrences = EventOccurrence.objects.filter(
            series=event.series
        ).order_by('start')

        # Verify occurrences are in chronological order
        prev_start = None
        for occurrence in occurrences:
            if prev_start:
                self.assertGreater(occurrence.start, prev_start)
            prev_start = occurrence.start

    def test_adhoc_series_with_different_durations(self):
        """Test adhoc series with varying slot durations"""
        slots = [
            {
                'start': self.tomorrow.isoformat(),
                'end': (self.tomorrow + timedelta(hours=1)).isoformat()
            },
            {
                'start': (self.tomorrow + timedelta(days=1)).isoformat(),
                'end': (self.tomorrow + timedelta(days=1, hours=3)).isoformat()
            }
        ]

        event = Event.objects.create_adhoc_series(
            title="Variable Length Workshop",
            sponsor=self.group,
            author=self.user1,
            adhoc_slots=slots
        )

        occurrences = EventOccurrence.objects.filter(
            series=event.series
        ).order_by('start')

        # First occurrence: 1 hour
        first = occurrences[0]
        first_duration = (first.end - first.start).total_seconds() / 3600
        self.assertEqual(first_duration, 1.0)

        # Second occurrence: 3 hours
        second = occurrences[1]
        second_duration = (second.end - second.start).total_seconds() / 3600
        self.assertEqual(second_duration, 3.0)


class EventMetadataTestCase(AlmanacTestMixin, TestCase):
    """Tests for event metadata and configuration"""

    def test_event_format_choices(self):
        """Test different event format types"""
        formats = ['workshop', 'lecture', 'discussion', 'social']

        for fmt in formats:
            event = self.create_test_event(
                title=f"Test {fmt}",
                event_format=fmt
            )
            self.assertEqual(event.event_format, fmt)

    def test_event_registration_required(self):
        """Test events with required registration"""
        event = self.create_test_event(
            registration_required=True,
            max_attendees=20
        )

        self.assertTrue(event.registration_required)
        self.assertEqual(event.max_attendees, 20)

    def test_event_location_optional(self):
        """Test that location is optional"""
        event = self.create_test_event(location=None)

        self.assertIsNone(event.location)

    def test_event_description_optional(self):
        """Test that description is optional"""
        event = self.create_test_event(description=None)

        self.assertIsNone(event.description)

    def test_event_default_status(self):
        """Test that new events default to draft status"""
        event = self.create_test_event()

        self.assertEqual(event.status, 'draft')

    def test_event_published_status(self):
        """Test publishing an event"""
        event = self.create_test_event()
        event.status = 'published'
        event.save()

        self.assertEqual(event.status, 'published')
