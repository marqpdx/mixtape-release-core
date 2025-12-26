"""
Occurrence Management Tests

Tests for managing individual occurrences within event series:
- Editing occurrences (title, location, time)
- Cancelling occurrences
- Occurrence status and properties
"""

from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from almanac.models import EventOccurrence, Event
from .fixtures import AlmanacTestMixin

User = get_user_model()


class OccurrenceEditingTestCase(AlmanacTestMixin, TestCase):
    """Tests for editing individual occurrences"""

    def test_edit_occurrence_title(self):
        """Test changing an occurrence's title"""
        event = self.create_recurring_event()
        occurrence = event.series.next_occurrence

        occurrence.title_override = "Special Session"
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.title_override, "Special Session")
        self.assertEqual(occurrence.effective_title, "Special Session")

    def test_edit_occurrence_location(self):
        """Test changing an occurrence's location"""
        event = self.create_test_event(location="Room A")
        occurrence = event.series.next_occurrence

        occurrence.location_override = "Room B"
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.location_override, "Room B")
        self.assertEqual(occurrence.effective_location, "Room B")

    def test_occurrence_without_override_uses_series_title(self):
        """Test that occurrences use series title when no override"""
        event = self.create_test_event(title="Weekly Meeting")
        occurrence = event.series.next_occurrence

        self.assertIsNone(occurrence.title_override)
        self.assertEqual(occurrence.effective_title, "Weekly Meeting")

    def test_edit_occurrence_start_time(self):
        """Test rescheduling an occurrence"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence
        original_start = occurrence.start

        new_start = original_start + timedelta(hours=2)
        new_end = occurrence.end + timedelta(hours=2)

        occurrence.start = new_start
        occurrence.end = new_end
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.start, new_start)
        self.assertEqual(occurrence.end, new_end)

    def test_cannot_set_end_before_start(self):
        """Test that end time must be after start time"""
        from django.db.utils import IntegrityError

        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # Try to set end before start
        occurrence.end = occurrence.start - timedelta(hours=1)

        # Should raise IntegrityError due to CHECK constraint
        with self.assertRaises(IntegrityError):
            occurrence.save()


class OccurrenceCancellationTestCase(AlmanacTestMixin, TestCase):
    """Tests for cancelling individual occurrences"""

    def test_cancel_occurrence(self):
        """Test cancelling a single occurrence"""
        event = self.create_recurring_event(rrule='FREQ=WEEKLY;COUNT=4')
        occurrence = event.series.next_occurrence

        occurrence.is_cancelled = True
        occurrence.cancellation_reason = "Bad weather"
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertTrue(occurrence.is_cancelled)
        self.assertEqual(occurrence.cancellation_reason, "Bad weather")

    def test_cancel_occurrence_without_reason(self):
        """Test cancelling without providing a reason"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        occurrence.is_cancelled = True
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertTrue(occurrence.is_cancelled)
        self.assertIsNone(occurrence.cancellation_reason)

    def test_cancelled_occurrences_still_queryable(self):
        """Test that cancelled occurrences remain in database"""
        event = self.create_recurring_event(rrule='FREQ=DAILY;COUNT=5')
        occurrences = EventOccurrence.objects.filter(series=event.series)
        first_occurrence = occurrences.first()

        first_occurrence.is_cancelled = True
        first_occurrence.save()

        # Should still be in database
        all_occurrences = EventOccurrence.objects.filter(series=event.series)
        cancelled_occurrences = all_occurrences.filter(is_cancelled=True)

        self.assertEqual(cancelled_occurrences.count(), 1)
        self.assertIn(first_occurrence, all_occurrences)

    def test_uncancel_occurrence(self):
        """Test that occurrences can be uncancelled"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # Cancel
        occurrence.is_cancelled = True
        occurrence.cancellation_reason = "Mistake"
        occurrence.save()

        # Uncancel
        occurrence.is_cancelled = False
        occurrence.cancellation_reason = None
        occurrence.save()

        occurrence.refresh_from_db()
        self.assertFalse(occurrence.is_cancelled)
        self.assertIsNone(occurrence.cancellation_reason)


class OccurrencePropertiesTestCase(AlmanacTestMixin, TestCase):
    """Tests for occurrence computed properties"""

    def test_is_past_property(self):
        """Test is_past property for past occurrences"""
        past_start = timezone.now() - timedelta(days=1)
        past_end = past_start + timedelta(hours=2)

        event = Event.objects.create_single_event(
            title="Past Event",
            sponsor=self.group,
            author=self.user1,
            start_time=past_start,
            end_time=past_end
        )

        occurrence = event.series.next_occurrence
        self.assertTrue(occurrence.is_past)

    def test_is_happening_now_property(self):
        """Test is_happening_now for current occurrences"""
        now = timezone.now()
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)

        event = Event.objects.create_single_event(
            title="Current Event",
            sponsor=self.group,
            author=self.user1,
            start_time=start,
            end_time=end
        )

        occurrence = event.series.next_occurrence
        self.assertTrue(occurrence.is_happening_now)

    def test_future_occurrence_properties(self):
        """Test properties for future occurrences"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        self.assertFalse(occurrence.is_past)
        self.assertFalse(occurrence.is_happening_now)

    def test_occurrence_attendee_count(self):
        """Test get_attendee_count method"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # Initially no attendees
        self.assertEqual(occurrence.get_attendee_count(), 0)

        # Add RSVPs
        self.create_rsvp(occurrence, self.user1, status='going')
        self.create_rsvp(occurrence, self.user2, status='going')

        self.assertEqual(occurrence.get_attendee_count(), 2)

    def test_occurrence_is_full_without_limit(self):
        """Test is_full when no max_attendees set"""
        event = self.create_test_event(max_attendees=None)
        occurrence = event.series.next_occurrence

        # Add many RSVPs
        for i in range(100):
            user = User.objects.create_user(
                username=f"user{i}",
                email=f"user{i}@test.com"
            )
            self.create_rsvp(occurrence, user, status='going')

        # Should never be full without a limit
        self.assertFalse(occurrence.is_full())

    def test_occurrence_is_full_with_limit(self):
        """Test is_full when max_attendees is set"""
        event = self.create_test_event(max_attendees=2)
        occurrence = event.series.next_occurrence

        # Add RSVPs up to limit
        self.create_rsvp(occurrence, self.user1, status='going')
        self.assertFalse(occurrence.is_full())

        self.create_rsvp(occurrence, self.user2, status='going')
        self.assertTrue(occurrence.is_full())


class OccurrenceQueryingTestCase(AlmanacTestMixin, TestCase):
    """Tests for querying occurrences"""

    def test_filter_by_date_range(self):
        """Test filtering occurrences by date range"""
        # Create events over 2 weeks
        for i in range(7):
            start = self.tomorrow + timedelta(days=i)
            end = start + timedelta(hours=1)
            Event.objects.create_single_event(
                title=f"Event Day {i}",
                sponsor=self.group,
                author=self.user1,
                start_time=start,
                end_time=end
            )

        # Query occurrences in a specific range
        range_start = self.tomorrow + timedelta(days=2)
        range_end = self.tomorrow + timedelta(days=5)

        occurrences = EventOccurrence.objects.filter(
            start__gte=range_start,
            start__lte=range_end
        )

        # Should get days 2, 3, 4, 5 = 4 occurrences
        self.assertEqual(occurrences.count(), 4)

    def test_filter_non_cancelled_occurrences(self):
        """Test filtering out cancelled occurrences"""
        event = self.create_recurring_event(rrule='FREQ=DAILY;COUNT=5')
        occurrences = EventOccurrence.objects.filter(series=event.series)

        # Cancel half of them
        for i, occurrence in enumerate(occurrences):
            if i % 2 == 0:
                occurrence.is_cancelled = True
                occurrence.save()

        active_occurrences = EventOccurrence.objects.filter(
            series=event.series,
            is_cancelled=False
        )

        # Should have about half remaining
        self.assertGreater(occurrences.count(), active_occurrences.count())

    def test_order_occurrences_by_start_time(self):
        """Test ordering occurrences chronologically"""
        event = self.create_recurring_event(rrule='FREQ=DAILY;COUNT=5')
        occurrences = EventOccurrence.objects.filter(
            series=event.series
        ).order_by('start')

        # Verify chronological order
        prev_start = None
        for occurrence in occurrences:
            if prev_start:
                self.assertGreaterEqual(occurrence.start, prev_start)
            prev_start = occurrence.start
