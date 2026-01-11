# almanac/tests/test_api_occurrences.py

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from almanac.models import Event, ContentStatus, OccurrenceAttendee
from .fixtures import AlmanacTestMixin


class AlmanacOccurrenceAPITests(AlmanacTestMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user1)

        self.event = Event.objects.create_single_event(
            title="Published Event",
            sponsor=self.group,
            author=self.user1,
            start_time=self.tomorrow,
            end_time=self.tomorrow + timezone.timedelta(hours=1),
        )
        self.event.status = ContentStatus.PUBLISHED
        self.event.published_at = timezone.now()
        self.event.save()
        self.occurrence = self.event.series.next_occurrence

    def test_occurrence_list_requires_auth(self):
        client = APIClient()
        response = client.get("/api/almanac/occurrences/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_occurrence_list_published_only(self):
        response = self.client.get("/api/almanac/occurrences/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.data["results"]}
        self.assertIn(self.occurrence.id, ids)

    def test_occurrence_detail(self):
        response = self.client.get(
            f"/api/almanac/occurrences/{self.occurrence.id}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.occurrence.id)

    def test_occurrence_rsvp_and_cancel(self):
        response = self.client.post(
            f"/api/almanac/occurrences/{self.occurrence.id}/rsvp",
            {"status": "going"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attendee = OccurrenceAttendee.objects.get(
            occurrence=self.occurrence,
            user=self.user1,
        )
        self.assertEqual(attendee.status, "going")

        cancel = self.client.post(
            f"/api/almanac/occurrences/{self.occurrence.id}/cancel-rsvp",
            {},
            format="json",
        )
        self.assertEqual(cancel.status_code, status.HTTP_200_OK)
        attendee.refresh_from_db()
        self.assertEqual(attendee.status, "not_going")
