from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from feedback.models import FeedbackBeacon, FeedbackItem


User = get_user_model()


class FeedbackApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="feedback_admin",
            email="feedback_admin@example.com",
            password="testpass123",
        )
        self.beacon = FeedbackBeacon.objects.create(
            key="writing-overview",
            title="Writing",
            is_active=True,
        )

    def test_post_feedback_items_creates_item_for_anonymous_user(self):
        response = self.client.post(
            "/api/feedback/items",
            {
                "beacon_key": self.beacon.key,
                "kind": FeedbackItem.Kind.BUG,
                "message": "Something broke in the editor.",
                "page_url": "/app/write",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = FeedbackItem.objects.get()
        self.assertEqual(item.beacon, self.beacon)
        self.assertEqual(item.kind, FeedbackItem.Kind.BUG)
        self.assertEqual(item.message, "Something broke in the editor.")
        self.assertEqual(item.page_url, "/app/write")
        self.assertIsNone(item.user)

    def test_post_feedback_items_attaches_authenticated_user(self):
        self.client.force_authenticate(self.user)

        response = self.client.post(
            "/api/feedback/items",
            {
                "beacon_key": self.beacon.key,
                "kind": FeedbackItem.Kind.IDEA,
                "message": "Would like better sorting.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = FeedbackItem.objects.get()
        self.assertEqual(item.user, self.user)

    def test_get_feedback_items_requires_authentication(self):
        response = self.client.get("/api/feedback/items")

        self.assertIn(
            response.status_code,
            {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN},
        )

    def test_get_feedback_items_returns_paginated_results_for_authenticated_user(self):
        self.client.force_authenticate(self.user)
        first = FeedbackItem.objects.create(
            beacon=self.beacon,
            kind=FeedbackItem.Kind.BUG,
            message="First",
            user=self.user,
        )
        second = FeedbackItem.objects.create(
            beacon=self.beacon,
            kind=FeedbackItem.Kind.REQUEST,
            message="Second",
            user=self.user,
        )

        response = self.client.get("/api/feedback/items?page=1&page_size=1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIn(response.data["results"][0]["id"], {first.id, second.id})

    def test_post_feedback_items_rejects_inactive_beacon(self):
        self.beacon.is_active = False
        self.beacon.save(update_fields=["is_active"])

        response = self.client.post(
            "/api/feedback/items",
            {
                "beacon_key": self.beacon.key,
                "kind": FeedbackItem.Kind.ISSUE,
                "message": "This should not be accepted.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(FeedbackItem.objects.count(), 0)
