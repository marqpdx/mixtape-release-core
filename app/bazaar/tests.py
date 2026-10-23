# bazaar/tests.py

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from rest_framework.test import APIClient

from bazaar.sponsors import sponsor_content_type


class SponsorTokenTests(TestCase):
    """Bazaar's sponsor tokens resolve through settings.SPONSOR_MODELS."""

    def test_user_and_member_resolve_to_the_user_model(self):
        user_ct = ContentType.objects.get_for_model(get_user_model(), for_concrete_model=False)
        self.assertEqual(sponsor_content_type("user"), user_ct)
        self.assertEqual(sponsor_content_type("member"), user_ct)

    def test_group_resolves_to_groups_group_not_auth_group(self):
        self.assertEqual(sponsor_content_type("group").app_label, "groups")

    def test_unknown_token_raises(self):
        with self.assertRaises(ObjectDoesNotExist):
            sponsor_content_type("nosuch")


class StallViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.member = get_user_model().objects.create_user(
            username="stall-keeper", email="stall@example.test", password="test"
        )

    def test_member_stall_is_found(self):
        response = self.client.get(f"/api/bazaar/stalls/user/{self.member.pk}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["offerings_count"], 0)

    def test_unknown_sponsor_is_not_found(self):
        response = self.client.get(f"/api/bazaar/stalls/user/{uuid4()}")
        self.assertEqual(response.status_code, 404)
