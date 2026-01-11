# almanac/tests/test_api_events.py

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from almanac.models import Event, ContentStatus
from .fixtures import AlmanacTestMixin


class AlmanacGroupEventAPITests(AlmanacTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user1)
        self.base_url = f"/api/groups/{self.group.slug}/almanac/"

    def test_group_event_create_single(self):
        payload = {
            "event_type": "single",
            "title": "API Single Event",
            "start_time": self.tomorrow.isoformat(),
            "end_time": (self.tomorrow + timezone.timedelta(hours=2)).isoformat(),
            "location": "Room 1",
            "event_format": "workshop",
        }
        response = self.client.post(self.base_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "API Single Event")
        self.assertEqual(response.data["status"], ContentStatus.DRAFT)

    def test_group_event_create_requires_times(self):
        payload = {
            "event_type": "single",
            "title": "Missing Times",
        }
        response = self.client.post(self.base_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_group_event_list(self):
        event = Event.objects.create_single_event(
            title="Listed Event",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data}
        self.assertIn(str(event.id), ids)

    def test_group_event_detail(self):
        event = Event.objects.create_single_event(
            title="Detail Event",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        response = self.client.get(f"{self.base_url}{event.slug}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(event.id))

    def test_group_event_update(self):
        event = Event.objects.create_single_event(
            title="Original Title",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        response = self.client.patch(
            f"{self.base_url}{event.slug}",
            {"title": "Updated Title"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Title")

    def test_group_event_publish_unpublish(self):
        event = Event.objects.create_single_event(
            title="Publish Event",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        publish = self.client.post(f"{self.base_url}{event.slug}/publish")
        self.assertEqual(publish.status_code, status.HTTP_200_OK)
        self.assertEqual(publish.data["status"], ContentStatus.PUBLISHED)

        unpublish = self.client.post(f"{self.base_url}{event.slug}/unpublish")
        self.assertEqual(unpublish.status_code, status.HTTP_200_OK)
        self.assertEqual(unpublish.data["status"], ContentStatus.DRAFT)

    def test_group_event_rsvp(self):
        event = Event.objects.create_single_event(
            title="RSVP Event",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        response = self.client.post(
            f"{self.base_url}{event.slug}/rsvp",
            {"status": "going"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "going")

    def test_group_event_requires_auth(self):
        client = APIClient()
        response = client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
