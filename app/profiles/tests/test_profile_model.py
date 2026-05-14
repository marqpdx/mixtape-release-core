from django.contrib.auth import get_user_model
from django.test import TestCase

from profiles.models import UserProfile


User = get_user_model()


class UserProfileModelTests(TestCase):
    def test_profile_slug_uses_display_name(self):
        user = User.objects.create_user(
            username="slug_owner",
            email="slug_owner@example.com",
            password="testpass123",
        )

        profile = UserProfile.objects.create(
            user=user,
            display_name="Example Person",
        )

        self.assertEqual(profile.slug, "example-person")

    def test_profile_slug_falls_back_to_username_and_remains_unique(self):
        first_user = User.objects.create_user(
            username="same-user",
            email="same1@example.com",
            password="testpass123",
        )
        second_user = User.objects.create_user(
            username="same-user-2",
            email="same2@example.com",
            password="testpass123",
        )

        first = UserProfile.objects.create(
            user=first_user,
            display_name="",
        )
        second = UserProfile.objects.create(
            user=second_user,
            display_name="same user",
        )

        self.assertEqual(first.slug, "same-user")
        self.assertEqual(second.slug, "same-user-1")
