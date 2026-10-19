from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from groups.models import Group
from relations.models import RelationshipType
from relations.service import RelationshipService
from tapestry.models import Location, Place

User = get_user_model()


class CommonsAdjacencyServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RelationshipType.objects.get_or_create(
            slug="adjacent",
            defaults={
                "label": "Adjacent to",
                "inverse_label": "Adjacent to",
                "domain": RelationshipType.DOMAIN_COMMONS,
                "is_directed": False,
                "uses_lifecycle": False,
            },
        )

    def setUp(self):
        self.author = User.objects.create_user(
            username="adjacency-author",
            email="adjacency-author@example.com",
            password="testpass123",
        )
        self.owner_group = Group.objects.create(
            title="Commons Curators", slug="commons-curators", group_type="community",
            decorators=[], additional_permissions=[],
            sponsor_content_type=ContentType.objects.get_for_model(User),
            sponsor_object_id=self.author.pk,
        )
        location = Location.objects.create(address="123 Main St")
        self.taco_cart = Place.objects.create(name="Taco Cart", location=location)
        self.noodle_cart = Place.objects.create(name="Noodle Cart", location=location)

    def test_create_and_read_back_one_adjacency_with_a_reason(self):
        relationship = RelationshipService.create_adjacency(
            source=self.taco_cart,
            target=self.noodle_cart,
            created_by=self.author,
            owner_group=self.owner_group,
            reason="Same lot, same food-cart pod",
        )

        self.assertEqual(relationship.relationship_type.slug, "adjacent")
        self.assertFalse(relationship.relationship_type.is_directed)
        self.assertEqual(relationship.notes, "Same lot, same food-cart pod")
        self.assertEqual(
            relationship.metadata[RelationshipService.ADJACENCY_OWNER_GROUP_ID_KEY],
            str(self.owner_group.pk),
        )

        relationship.refresh_from_db()
        self.assertEqual(relationship.source_object_id, self.taco_cart.pk)
        self.assertEqual(relationship.target_object_id, self.noodle_cart.pk)
        self.assertEqual(relationship.notes, "Same lot, same food-cart pod")
