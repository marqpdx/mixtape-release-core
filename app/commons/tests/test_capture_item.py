from django.contrib.auth import get_user_model
from django.test import TestCase

from commons.models import CommonsItem
from commons.services import capture_item

User = get_user_model()


class CaptureItemTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="commons-capturer",
            email="commons-capturer@example.com",
            password="testpass123",
        )

    def test_capture_item_has_no_curation_lifecycle(self):
        self.assertFalse(hasattr(CommonsItem, "CurationStatus"))
        item = capture_item(user=self.user, title="Choir! Choir! Choir!")
        self.assertFalse(hasattr(item, "curation_status"))
        self.assertFalse(hasattr(item, "curated_by"))
        self.assertFalse(hasattr(item, "approved_by"))

    def test_capture_item_is_published_on_capture(self):
        """D5: a thing exists only once approved, so it is published when it exists."""
        item = capture_item(user=self.user, title="Choir! Choir! Choir!")
        self.assertIsNotNone(item.published_at)

    def test_capture_item_keeps_human_recommendation_fields(self):
        item = capture_item(
            user=self.user,
            title="Choir! Choir! Choir!",
            why_recommended="Strangers singing in harmony in a bar.",
        )
        self.assertEqual(item.recommended_by_id, self.user.id)
        self.assertEqual(item.why_recommended, "Strangers singing in harmony in a bar.")
