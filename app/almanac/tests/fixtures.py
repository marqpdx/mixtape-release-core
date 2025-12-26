"""
Test Fixtures and Utilities for Almanac Tests

Provides reusable test data creation functions and base test case classes.
"""

from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.utils import timezone
from groups.models import Group, GroupMembership
from almanac.models import Event, EventSeries, EventOccurrence, OccurrenceAttendee

User = get_user_model()


class AlmanacTestMixin:
    """
    Mixin providing common test fixtures and utilities for Almanac tests.

    Usage:
        class MyTestCase(AlmanacTestMixin, TestCase):
            def test_something(self):
                event = self.create_test_event()
                ...
    """

    def setUp(self):
        """Create base test fixtures"""
        super().setUp()

        # Create test users
        self.user1 = User.objects.create_user(
            username="testuser1",
            email="user1@test.com",
            password="testpass123"
        )
        self.user2 = User.objects.create_user(
            username="testuser2",
            email="user2@test.com",
            password="testpass123"
        )
        self.organizer = User.objects.create_user(
            username="organizer",
            email="organizer@test.com",
            password="testpass123"
        )

        # Create test group (sponsor will be set after creation for self-sponsorship)
        self.group = Group.objects.create(
            title="Test Group",
            slug="test-group",
            description="Test group for events",
            group_type="community",
            decorators=[],
            additional_permissions=[],
            sponsor=self.user1  # Sponsor by first user
        )

        # Add members to group
        GroupMembership.objects.create(
            group=self.group,
            member_object=self.user1,
            roles=["member"]
        )
        GroupMembership.objects.create(
            group=self.group,
            member_object=self.user2,
            roles=["member"]
        )
        GroupMembership.objects.create(
            group=self.group,
            member_object=self.organizer,
            roles=["member", "editor"]
        )

        # Default datetime values for tests
        self.now = timezone.now()
        self.tomorrow = self.now + timedelta(days=1)
        self.next_week = self.now + timedelta(days=7)

    def create_test_event(self, **kwargs):
        """
        Create a single test event with sensible defaults.

        Args:
            **kwargs: Override default event attributes

        Returns:
            Event instance
        """
        defaults = {
            'title': 'Test Event',
            'description': 'Test event description',
            'location': 'Test Location',
            'event_format': 'workshop',
            'sponsor': self.group,
            'author': self.user1,
            'start_time': self.tomorrow.replace(hour=14, minute=0, second=0, microsecond=0),
            'end_time': self.tomorrow.replace(hour=16, minute=0, second=0, microsecond=0),
        }
        defaults.update(kwargs)

        return Event.objects.create_single_event(**defaults)

    def create_recurring_event(self, **kwargs):
        """
        Create a recurring test event with sensible defaults.

        Args:
            **kwargs: Override default event attributes

        Returns:
            Event instance
        """
        defaults = {
            'title': 'Recurring Test Event',
            'description': 'Recurring test event',
            'location': 'Test Location',
            'event_format': 'workshop',
            'sponsor': self.group,
            'author': self.user1,
            'start_time': self.tomorrow.replace(hour=14, minute=0, second=0, microsecond=0),
            'end_time': self.tomorrow.replace(hour=16, minute=0, second=0, microsecond=0),
            'rrule': 'FREQ=WEEKLY;COUNT=4',  # 4 weekly occurrences
            'timezone': 'UTC',
            'default_duration_minutes': 120,
        }
        defaults.update(kwargs)

        return Event.objects.create_recurring_event(**defaults)

    def create_adhoc_series(self, num_slots=3, **kwargs):
        """
        Create an adhoc series event with custom time slots.

        Args:
            num_slots: Number of time slots to create
            **kwargs: Override default event attributes

        Returns:
            Event instance
        """
        # Generate time slots
        slots = []
        for i in range(num_slots):
            start = self.tomorrow + timedelta(days=i*2)
            end = start + timedelta(hours=2)
            slots.append({
                'start': start.isoformat(),
                'end': end.isoformat()
            })

        defaults = {
            'title': 'Adhoc Series Event',
            'description': 'Test adhoc series',
            'location': 'Test Location',
            'event_format': 'workshop',
            'sponsor': self.group,
            'author': self.user1,
            'adhoc_slots': slots,
        }
        defaults.update(kwargs)

        return Event.objects.create_adhoc_series(**defaults)

    def create_rsvp(self, occurrence, user, status='going', **kwargs):
        """
        Create an RSVP for an occurrence.

        Args:
            occurrence: EventOccurrence instance
            user: User instance
            status: RSVP status ('going', 'maybe', 'not_going')
            **kwargs: Additional OccurrenceAttendee attributes

        Returns:
            OccurrenceAttendee instance
        """
        defaults = {
            'occurrence': occurrence,
            'user': user,
            'status': status,
        }
        defaults.update(kwargs)

        return OccurrenceAttendee.objects.create(**defaults)

    def get_future_occurrences(self, event):
        """Get all future occurrences for an event"""
        return EventOccurrence.objects.filter(
            series=event.series,
            start__gte=timezone.now()
        ).order_by('start')

    def get_past_occurrences(self, event):
        """Get all past occurrences for an event"""
        return EventOccurrence.objects.filter(
            series=event.series,
            start__lt=timezone.now()
        ).order_by('start')


# Standalone utility functions for use outside of test cases

def create_test_user(username="testuser", email=None, password="testpass123"):
    """Create a test user with minimal setup"""
    if email is None:
        email = f"{username}@test.com"

    return User.objects.create_user(
        username=username,
        email=email,
        password=password
    )


def create_test_group(title="Test Group", slug=None, sponsor=None):
    """Create a test group with minimal setup"""
    if slug is None:
        slug = title.lower().replace(' ', '-')

    if sponsor is None:
        sponsor = create_test_user(username=f"{slug}-owner")

    return Group.objects.create(
        title=title,
        slug=slug,
        description=f"Test group: {title}",
        group_type="community",
        decorators=[],
        additional_permissions=[],
        sponsor=sponsor
    )


def create_published_event(group, author, days_ahead=1):
    """Create a published event ready for public viewing"""
    start_time = timezone.now() + timedelta(days=days_ahead)
    end_time = start_time + timedelta(hours=2)

    event = Event.objects.create_single_event(
        title="Published Event",
        description="A published test event",
        location="Test Location",
        event_format="workshop",
        sponsor=group,
        author=author,
        start_time=start_time,
        end_time=end_time,
    )

    # Publish the event
    event.status = 'published'
    event.save()

    return event
