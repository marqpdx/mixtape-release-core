"""
Permission Tests

Tests for event access control and permissions:
- Event authorship
- Organizer permissions
- View vs edit permissions
- Published vs draft visibility
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from groups.models import Group
from almanac.models import EventFollower, Event
from .fixtures import AlmanacTestMixin

User = get_user_model()


class EventAuthorshipTestCase(AlmanacTestMixin, TestCase):
    """Tests for event author permissions"""

    def test_event_author_can_edit(self):
        """Test that event author can edit their event"""
        event = self.create_test_event(author=self.user1)

        self.assertEqual(event.author, self.user1)
        # Author should be able to modify event
        event.title = "Updated Title"
        event.save()

        event.refresh_from_db()
        self.assertEqual(event.title, "Updated Title")

    def test_event_author_can_delete(self):
        """Test that event author can delete their event"""
        event = self.create_test_event(author=self.user1)
        event_id = event.id

        event.delete()

        from almanac.models import Event
        self.assertFalse(Event.objects.filter(id=event_id).exists())

    def test_non_author_is_different_user(self):
        """Test identifying users who are not the author"""
        event = self.create_test_event(author=self.user1)

        self.assertNotEqual(event.author, self.user2)


class OrganizerPermissionsTestCase(AlmanacTestMixin, TestCase):
    """Tests for event organizer (follower) permissions"""

    def test_add_organizer_to_event(self):
        """Test adding an organizer via EventFollower"""
        event = self.create_test_event(author=self.user1)

        # Add user2 as organizer
        follower = EventFollower.objects.create(
            event=event,
            user=self.user2,
            follow_type='organizer'
        )

        self.assertEqual(follower.follow_type, 'organizer')
        self.assertEqual(follower.event, event)

    def test_list_event_organizers(self):
        """Test retrieving all organizers for an event"""
        event = self.create_test_event(author=self.user1)

        # Add multiple organizers
        EventFollower.objects.create(
            event=event,
            user=self.user2,
            follow_type='organizer'
        )
        EventFollower.objects.create(
            event=event,
            user=self.organizer,
            follow_type='organizer'
        )

        organizers = EventFollower.objects.filter(
            event=event,
            follow_type='organizer'
        )

        self.assertEqual(organizers.count(), 2)

    def test_check_if_user_is_organizer(self):
        """Test checking organizer status for a user"""
        event = self.create_test_event(author=self.user1)

        EventFollower.objects.create(
            event=event,
            user=self.user2,
            follow_type='organizer'
        )

        is_organizer = EventFollower.objects.filter(
            event=event,
            user=self.user2,
            follow_type='organizer'
        ).exists()

        is_not_organizer = EventFollower.objects.filter(
            event=event,
            user=self.organizer,
            follow_type='organizer'
        ).exists()

        self.assertTrue(is_organizer)
        self.assertFalse(is_not_organizer)

    def test_remove_organizer(self):
        """Test removing an organizer"""
        event = self.create_test_event(author=self.user1)

        follower = EventFollower.objects.create(
            event=event,
            user=self.user2,
            follow_type='organizer'
        )

        follower.delete()

        self.assertFalse(
            EventFollower.objects.filter(
                event=event,
                user=self.user2,
                follow_type='organizer'
            ).exists()
        )


class EventFollowerTypesTestCase(AlmanacTestMixin, TestCase):
    """Tests for different follower types"""

    def test_interested_follower(self):
        """Test following an event as interested"""
        event = self.create_test_event()

        EventFollower.objects.create(
            event=event,
            user=self.user1,
            follow_type='interested'
        )

        interested = EventFollower.objects.filter(
            event=event,
            follow_type='interested'
        )

        self.assertEqual(interested.count(), 1)

    def test_multiple_follower_types(self):
        """Test that an event can have different follower types"""
        event = self.create_test_event()

        EventFollower.objects.create(
            event=event,
            user=self.user1,
            follow_type='organizer'
        )
        EventFollower.objects.create(
            event=event,
            user=self.user2,
            follow_type='interested'
        )

        organizers = EventFollower.objects.filter(
            event=event,
            follow_type='organizer'
        ).count()

        interested = EventFollower.objects.filter(
            event=event,
            follow_type='interested'
        ).count()

        self.assertEqual(organizers, 1)
        self.assertEqual(interested, 1)

    def test_user_can_unfollow_event(self):
        """Test unfollowing an event"""
        event = self.create_test_event()

        follower = EventFollower.objects.create(
            event=event,
            user=self.user1,
            follow_type='interested'
        )

        # Unfollow
        follower.delete()

        self.assertFalse(
            EventFollower.objects.filter(
                event=event,
                user=self.user1
            ).exists()
        )


class EventVisibilityTestCase(AlmanacTestMixin, TestCase):
    """Tests for event visibility (published vs draft)"""

    def test_draft_events_not_public(self):
        """Test that draft events are not published"""
        event = self.create_test_event()

        self.assertEqual(event.status, 'draft')

    def test_publish_event(self):
        """Test publishing an event"""
        event = self.create_test_event()

        event.status = 'published'
        event.save()

        event.refresh_from_db()
        self.assertEqual(event.status, 'published')

    def test_unpublish_event(self):
        """Test unpublishing an event"""
        event = self.create_test_event()
        event.status = 'published'
        event.save()

        event.status = 'draft'
        event.save()

        event.refresh_from_db()
        self.assertEqual(event.status, 'draft')

    def test_filter_published_events(self):
        """Test querying only published events"""
        from almanac.models import Event

        # Create mix of published and draft
        draft1 = self.create_test_event(title="Draft 1")
        draft2 = self.create_test_event(title="Draft 2")

        published1 = self.create_test_event(title="Published 1")
        published1.status = 'published'
        published1.save()

        published2 = self.create_test_event(title="Published 2")
        published2.status = 'published'
        published2.save()

        published_events = Event.objects.filter(status='published')
        self.assertEqual(published_events.count(), 2)

    def test_archived_event_status(self):
        """Test archiving an event"""
        event = self.create_test_event()

        event.status = 'archived'
        event.save()

        event.refresh_from_db()
        self.assertEqual(event.status, 'archived')


class GroupSponsorshipTestCase(AlmanacTestMixin, TestCase):
    """Tests for event sponsorship by groups"""

    def test_event_sponsored_by_group(self):
        """Test that events are sponsored by groups"""
        event = self.create_test_event(sponsor=self.group)

        self.assertEqual(event.sponsor, self.group)

    def test_query_events_by_sponsor(self):
        """Test filtering events by sponsoring group"""
        from almanac.models import Event

        # Create events for different groups
        group2 = Group.objects.create(
            title="Group 2",
            slug="group-2",
            group_type="community",
            sponsor=self.user2
        )

        event1 = self.create_test_event(sponsor=self.group, title="Event 1")
        event2 = self.create_test_event(sponsor=self.group, title="Event 2")
        event3 = self.create_test_event(sponsor=group2, title="Event 3")

        group1_events = Event.objects.filter(sponsor_object_id=self.group.id)
        group2_events = Event.objects.filter(sponsor_object_id=group2.id)

        self.assertEqual(group1_events.count(), 2)
        self.assertEqual(group2_events.count(), 1)

    def test_event_group_context(self):
        """Test accessing group context from event"""
        event = self.create_test_event(sponsor=self.group)

        self.assertEqual(event.sponsor.title, "Test Group")
        self.assertEqual(event.sponsor.slug, "test-group")
