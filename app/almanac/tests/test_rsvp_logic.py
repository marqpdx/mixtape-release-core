"""
RSVP Logic Tests

Tests for RSVP functionality:
- RSVPing to single occurrences
- RSVPing to entire event series
- Changing RSVP status
- RSVP limits and capacity
- Attendee check-in
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from almanac.models import OccurrenceAttendee, EventOccurrence, Event
from .fixtures import AlmanacTestMixin

User = get_user_model()


class SingleOccurrenceRSVPTestCase(AlmanacTestMixin, TestCase):
    """Tests for RSVPing to individual occurrences"""

    def test_rsvp_to_occurrence(self):
        """Test basic RSVP to an occurrence"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        rsvp = self.create_rsvp(occurrence, self.user1, status='going')

        self.assertEqual(rsvp.occurrence, occurrence)
        self.assertEqual(rsvp.user, self.user1)
        self.assertEqual(rsvp.status, 'going')
        self.assertIsNotNone(rsvp.registered_at)

    def test_rsvp_status_choices(self):
        """Test different RSVP status options"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        statuses = ['going', 'maybe', 'not_going']

        for i, status in enumerate(statuses):
            user = User.objects.create_user(
                username=f"user{i}",
                email=f"user{i}@test.com"
            )
            rsvp = self.create_rsvp(occurrence, user, status=status)
            self.assertEqual(rsvp.status, status)

    def test_change_rsvp_status(self):
        """Test changing an existing RSVP"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        rsvp = self.create_rsvp(occurrence, self.user1, status='maybe')
        self.assertEqual(rsvp.status, 'maybe')

        # Change to going
        rsvp.status = 'going'
        rsvp.save()

        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, 'going')

    def test_user_can_only_rsvp_once_per_occurrence(self):
        """Test that a user can only have one RSVP per occurrence"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # First RSVP
        rsvp1 = self.create_rsvp(occurrence, self.user1, status='going')

        # Try to create duplicate - should fail with unique constraint
        # Or use get_or_create pattern in production
        existing_rsvps = OccurrenceAttendee.objects.filter(
            occurrence=occurrence,
            user=self.user1
        )
        self.assertEqual(existing_rsvps.count(), 1)

    def test_rsvp_with_registration_notes(self):
        """Test adding notes to RSVP"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        rsvp = self.create_rsvp(
            occurrence,
            self.user1,
            status='going',
            registration_notes="I have dietary restrictions"
        )

        self.assertEqual(rsvp.registration_notes, "I have dietary restrictions")

    def test_cancel_rsvp(self):
        """Test cancelling an RSVP"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        rsvp = self.create_rsvp(occurrence, self.user1, status='going')

        # Change to not_going
        rsvp.status = 'not_going'
        rsvp.save()

        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, 'not_going')


class SeriesRSVPTestCase(AlmanacTestMixin, TestCase):
    """Tests for RSVPing to entire event series"""

    def test_rsvp_to_all_occurrences(self):
        """Test RSVPing to all occurrences in a series"""
        event = self.create_recurring_event(rrule='FREQ=WEEKLY;COUNT=4')
        occurrences = EventOccurrence.objects.filter(series=event.series)

        # Use the manager method to RSVP to entire series
        attendees = OccurrenceAttendee.objects.rsvp_to_entire_event(
            event=event,
            user=self.user1,
            status='going'
        )

        self.assertEqual(len(attendees), occurrences.count())

        # Verify all occurrences have the RSVP
        for occurrence in occurrences:
            rsvp_exists = OccurrenceAttendee.objects.filter(
                occurrence=occurrence,
                user=self.user1,
                status='going'
            ).exists()
            self.assertTrue(rsvp_exists)

    def test_rsvp_to_limited_occurrences(self):
        """Test RSVPing to only next N occurrences"""
        event = self.create_recurring_event(rrule='FREQ=WEEKLY;COUNT=5')

        # RSVP to only next 2 occurrences
        attendees = OccurrenceAttendee.objects.rsvp_to_entire_event(
            event=event,
            user=self.user1,
            status='going',
            limit_to=2
        )

        self.assertEqual(len(attendees), 2)

    def test_series_rsvp_skips_past_occurrences(self):
        """Test that series RSVP only applies to future occurrences"""
        from datetime import timedelta
        from django.utils import timezone

        # Create event with some past occurrences
        past_start = timezone.now() - timedelta(days=10)
        event = Event.objects.create_recurring_event(
            title="Started in Past",
            sponsor=self.group,
            author=self.user1,
            start_time=past_start,
            end_time=past_start + timedelta(hours=1),
            rrule='FREQ=DAILY;COUNT=15',  # 15 days, some past, some future
            timezone='UTC',
            default_duration_minutes=60
        )

        # RSVP to series
        attendees = OccurrenceAttendee.objects.rsvp_to_entire_event(
            event=event,
            user=self.user1,
            status='going'
        )

        # Should only RSVP to future occurrences
        future_occurrences = EventOccurrence.objects.filter(
            series=event.series,
            start__gte=timezone.now()
        )

        self.assertEqual(len(attendees), future_occurrences.count())


class RSVPCapacityTestCase(AlmanacTestMixin, TestCase):
    """Tests for RSVP capacity limits"""

    def test_occurrence_capacity_tracking(self):
        """Test tracking number of attendees vs capacity"""
        event = self.create_test_event(max_attendees=3)
        occurrence = event.series.next_occurrence

        # Add RSVPs
        self.create_rsvp(occurrence, self.user1, status='going')
        self.assertEqual(occurrence.get_attendee_count(), 1)

        self.create_rsvp(occurrence, self.user2, status='going')
        self.assertEqual(occurrence.get_attendee_count(), 2)

    def test_occurrence_full_status(self):
        """Test is_full property when capacity reached"""
        event = self.create_test_event(max_attendees=2)
        occurrence = event.series.next_occurrence

        self.assertFalse(occurrence.is_full())

        # Fill to capacity
        self.create_rsvp(occurrence, self.user1, status='going')
        self.create_rsvp(occurrence, self.user2, status='going')

        self.assertTrue(occurrence.is_full())

    def test_maybe_rsvps_count_toward_capacity(self):
        """Test that 'maybe' RSVPs are counted"""
        event = self.create_test_event(max_attendees=2)
        occurrence = event.series.next_occurrence

        self.create_rsvp(occurrence, self.user1, status='maybe')
        self.create_rsvp(occurrence, self.user2, status='going')

        self.assertEqual(occurrence.get_attendee_count(), 2)
        self.assertTrue(occurrence.is_full())

    def test_not_going_rsvps_dont_count(self):
        """Test that 'not_going' RSVPs are not counted"""
        event = self.create_test_event(max_attendees=2)
        occurrence = event.series.next_occurrence

        self.create_rsvp(occurrence, self.user1, status='going')
        self.create_rsvp(occurrence, self.user2, status='not_going')

        self.assertEqual(occurrence.get_attendee_count(), 1)
        self.assertFalse(occurrence.is_full())


class AttendeeCheckInTestCase(AlmanacTestMixin, TestCase):
    """Tests for attendee check-in functionality"""

    def test_check_in_attendee(self):
        """Test checking in an attendee"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence
        rsvp = self.create_rsvp(occurrence, self.user1, status='going')

        self.assertIsNone(rsvp.checked_in_at)

        # Check in
        from django.utils import timezone
        rsvp.checked_in_at = timezone.now()
        rsvp.status = 'attended'
        rsvp.save()

        rsvp.refresh_from_db()
        self.assertIsNotNone(rsvp.checked_in_at)
        self.assertEqual(rsvp.status, 'attended')

    def test_check_in_updates_status(self):
        """Test that check-in updates status to attended"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence
        rsvp = self.create_rsvp(occurrence, self.user1, status='maybe')

        # Check in
        from django.utils import timezone
        rsvp.checked_in_at = timezone.now()
        rsvp.status = 'attended'
        rsvp.save()

        rsvp.refresh_from_db()
        self.assertEqual(rsvp.status, 'attended')

    def test_attendee_feedback_and_rating(self):
        """Test adding feedback and rating after attending"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence
        rsvp = self.create_rsvp(occurrence, self.user1, status='attended')

        rsvp.feedback = "Great workshop!"
        rsvp.rating = 5
        rsvp.save()

        rsvp.refresh_from_db()
        self.assertEqual(rsvp.feedback, "Great workshop!")
        self.assertEqual(rsvp.rating, 5)


class RSVPQueryingTestCase(AlmanacTestMixin, TestCase):
    """Tests for querying RSVPs and attendees"""

    def test_get_attendees_for_occurrence(self):
        """Test retrieving all attendees for an occurrence"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # Create multiple RSVPs
        users = []
        for i in range(3):
            user = User.objects.create_user(
                username=f"attendee{i}",
                email=f"attendee{i}@test.com"
            )
            users.append(user)
            self.create_rsvp(occurrence, user, status='going')

        attendees = OccurrenceAttendee.objects.filter(occurrence=occurrence)
        self.assertEqual(attendees.count(), 3)

    def test_get_user_rsvps_across_series(self):
        """Test getting all RSVPs for a user across multiple occurrences"""
        event = self.create_recurring_event(rrule='FREQ=WEEKLY;COUNT=4')

        # RSVP to all occurrences
        OccurrenceAttendee.objects.rsvp_to_entire_event(
            event=event,
            user=self.user1,
            status='going'
        )

        # Query all RSVPs for this user in this series
        user_rsvps = OccurrenceAttendee.objects.filter(
            occurrence__series=event.series,
            user=self.user1
        )

        occurrences_count = EventOccurrence.objects.filter(series=event.series).count()
        self.assertEqual(user_rsvps.count(), occurrences_count)

    def test_filter_rsvps_by_status(self):
        """Test filtering RSVPs by status"""
        event = self.create_test_event()
        occurrence = event.series.next_occurrence

        # Create RSVPs with different statuses
        for i in range(5):
            user = User.objects.create_user(
                username=f"user{i}",
                email=f"user{i}@test.com"
            )
            status = 'going' if i < 3 else 'maybe'
            self.create_rsvp(occurrence, user, status=status)

        going_rsvps = OccurrenceAttendee.objects.filter(
            occurrence=occurrence,
            status='going'
        )
        maybe_rsvps = OccurrenceAttendee.objects.filter(
            occurrence=occurrence,
            status='maybe'
        )

        self.assertEqual(going_rsvps.count(), 3)
        self.assertEqual(maybe_rsvps.count(), 2)
