from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from profiles.models import UserProfile


User = get_user_model()


class MemberApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(
            username="profile_owner",
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="User",
        )
        self.other_user = User.objects.create_user(
            username="profile_other",
            email="other@example.com",
            password="testpass123",
            first_name="Other",
            last_name="User",
        )
        self.staff_user = User.objects.create_user(
            username="profile_staff",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.inactive_user = User.objects.create_user(
            username="profile_inactive",
            email="inactive@example.com",
            password="testpass123",
            is_active=False,
        )

        self.owner_profile = UserProfile.objects.create(
            user=self.owner,
            display_name="Owner Display",
            quick_intro="Owner intro",
            preferences={"layout": "grid"},
        )
        self.other_profile = UserProfile.objects.create(
            user=self.other_user,
            display_name="Other Display",
            quick_intro="Other intro",
            preferences={"theme": "light"},
        )
        self.staff_profile = UserProfile.objects.create(
            user=self.staff_user,
            display_name="Staff Display",
            quick_intro="Staff intro",
        )
        self.inactive_profile = UserProfile.objects.create(
            user=self.inactive_user,
            display_name="Inactive Display",
            quick_intro="Should be hidden",
        )

    def test_member_list_is_public_and_excludes_inactive_and_soft_deleted_profiles(self):
        self.other_profile.deleted_at = self.other_profile.created_at
        self.other_profile.save(update_fields=["deleted_at", "updated_at"])

        response = self.client.get("/api/members/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data.get("results") if isinstance(response.data, dict) else response.data
        usernames = {row["username"] for row in payload}
        self.assertIn(self.owner.username, usernames)
        self.assertIn(self.staff_user.username, usernames)
        self.assertNotIn(self.other_user.username, usernames)
        self.assertNotIn(self.inactive_user.username, usernames)

    def test_member_me_requires_authentication(self):
        response = self.client.get("/api/members/me")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_member_me_returns_authenticated_profile(self):
        self.client.force_authenticate(self.owner)

        response = self.client.get("/api/members/me")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.owner.username)
        self.assertEqual(response.data["display_name"], self.owner_profile.display_name)

    def test_member_detail_is_public(self):
        response = self.client.get(f"/api/members/{self.owner.username}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], self.owner.username)
        self.assertEqual(response.data["display_name"], self.owner_profile.display_name)

    def test_member_detail_patch_requires_owner_or_staff(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.patch(
            f"/api/members/{self.owner.username}",
            {"display_name": "Blocked Update"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.display_name, "Owner Display")

    def test_member_detail_patch_updates_profile_for_owner(self):
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            f"/api/members/{self.owner.username}",
            {
                "display_name": "Updated Owner",
                "quick_intro": "Updated intro",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.display_name, "Updated Owner")
        self.assertEqual(self.owner_profile.quick_intro, "Updated intro")

    def test_member_detail_patch_allows_staff(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.patch(
            f"/api/members/{self.owner.username}",
            {"display_name": "Staff Updated"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.display_name, "Staff Updated")

    def test_member_detail_delete_soft_deletes_profile(self):
        self.client.force_authenticate(self.owner)

        response = self.client.delete(f"/api/members/{self.owner.username}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.owner_profile.refresh_from_db()
        self.assertIsNotNone(self.owner_profile.deleted_at)

        public_response = self.client.get(f"/api/members/{self.owner.username}")
        self.assertEqual(public_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_member_preferences_requires_authentication(self):
        response = self.client.get("/api/members/me/preferences")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_member_preferences_get_and_patch_merge_updates(self):
        self.client.force_authenticate(self.owner)

        get_response = self.client.get("/api/members/me/preferences")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data, {"layout": "grid"})

        patch_response = self.client.patch(
            "/api/members/me/preferences",
            {"theme": "dark"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data, {"layout": "grid", "theme": "dark"})

        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.preferences, {"layout": "grid", "theme": "dark"})

    def test_member_preferences_patch_rejects_non_object_payload(self):
        self.client.force_authenticate(self.owner)

        response = self.client.patch(
            "/api/members/me/preferences",
            ["not", "a", "dict"],
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Expected a JSON object.")
