from django.contrib.auth import get_user_model
from django.test import TestCase

from commons.models import Leaf
from relations.models import Relationship, RelationshipType
from relations.service import RelationshipConstraintError, RelationshipService

User = get_user_model()


class RelationshipTypeConstraintTests(TestCase):
    """ADR-0042 invariant 6: constraints are enforced by the service."""

    @classmethod
    def setUpTestData(cls):
        cls.constrained, _ = RelationshipType.objects.update_or_create(
            slug="constraint-test-leaf-to-user",
            defaults={
                "label": "Presence test",
                "domain": RelationshipType.DOMAIN_COMMONS,
                "valid_source_types": ["commons.Leaf"],
                "valid_target_types": ["users.CustomUser"],
            },
        )
        cls.open_type, _ = RelationshipType.objects.update_or_create(
            slug="constraint-test-open",
            defaults={"label": "Open test", "domain": RelationshipType.DOMAIN_COMMONS},
        )

    def setUp(self):
        self.author = User.objects.create_user(
            username="constraint-author", email="constraint@example.com", password="testpass123"
        )
        self.leaf = Leaf.objects.create(author=self.author)

    def test_matching_endpoints_are_accepted(self):
        relationship = RelationshipService.create_relationship(
            type_slug=self.constrained.slug, source=self.leaf, target=self.author, created_by=self.author
        )
        self.assertEqual(relationship.relationship_type, self.constrained)

    def test_wrong_source_model_is_rejected_and_nothing_is_written(self):
        before = Relationship.objects.count()
        with self.assertRaises(RelationshipConstraintError):
            RelationshipService.create_relationship(
                type_slug=self.constrained.slug, source=self.author, target=self.author, created_by=self.author
            )
        self.assertEqual(Relationship.objects.count(), before)

    def test_wrong_target_model_is_rejected(self):
        with self.assertRaises(RelationshipConstraintError):
            RelationshipService.create_relationship(
                type_slug=self.constrained.slug, source=self.leaf, target=self.leaf, created_by=self.author
            )

    def test_an_empty_constraint_allows_any_model(self):
        RelationshipService.create_relationship(
            type_slug=self.open_type.slug, source=self.author, target=self.leaf, created_by=self.author
        )

    def test_constraint_labels_match_case_insensitively(self):
        RelationshipType.objects.filter(pk=self.constrained.pk).update(
            valid_source_types=["COMMONS.leaf"], valid_target_types=["Users.CustomUser"]
        )
        RelationshipService.create_relationship(
            type_slug=self.constrained.slug, source=self.leaf, target=self.author, created_by=self.author
        )
