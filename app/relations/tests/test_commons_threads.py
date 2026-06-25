from django.contrib.auth import get_user_model
from django.test import TestCase

from relations.models import Relationship, RelationshipType
from relations.service import RelationshipService
from commons.models import Leaf


User = get_user_model()


class CommonsThreadServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RelationshipType.objects.get_or_create(
            slug="continues",
            defaults={
                "label": "Continues",
                "domain": RelationshipType.DOMAIN_COMMONS,
                "allows_position": True,
                "uses_lifecycle": False,
            },
        )

    def setUp(self):
        self.author = User.objects.create_user(
            username="commons-thread-author",
            email="commons-thread@example.com",
            password="testpass123",
        )
        self.leaves = [Leaf.objects.create(author=self.author) for _ in range(3)]

    def test_continue_thread_mints_and_reuses_thread_metadata(self):
        first = RelationshipService.continue_thread(
            from_leaf=self.leaves[0],
            to_leaf=self.leaves[1],
            created_by=self.author,
            position=2,
            thread_title="Field notes",
        )
        thread_id = first.metadata[RelationshipService.THREAD_ID_KEY]

        self.assertTrue(thread_id)
        self.assertEqual(
            first.metadata[RelationshipService.THREAD_TITLE_KEY], "Field notes"
        )
        self.assertFalse(first.metadata[RelationshipService.THREAD_CLOSED_KEY])

        second = RelationshipService.continue_thread(
            from_leaf=self.leaves[1],
            to_leaf=self.leaves[2],
            created_by=self.author,
            position=1,
            thread_id=thread_id,
            thread_title="Field notes",
        )

        self.assertEqual(
            second.metadata[RelationshipService.THREAD_ID_KEY], thread_id
        )
        self.assertEqual(
            list(
                RelationshipService.get_thread(thread_id).values_list(
                    "position", flat=True
                )
            ),
            [1, 2],
        )

    def test_closed_thread_rejects_new_relationships(self):
        relationship = RelationshipService.continue_thread(
            from_leaf=self.leaves[0],
            to_leaf=self.leaves[1],
            created_by=self.author,
            position=1,
        )
        thread_id = relationship.metadata[RelationshipService.THREAD_ID_KEY]

        self.assertFalse(RelationshipService.is_thread_closed(None))
        self.assertEqual(RelationshipService.close_thread(thread_id=thread_id), 1)
        self.assertTrue(RelationshipService.is_thread_closed(thread_id))

        relationship.refresh_from_db()
        self.assertTrue(
            relationship.metadata[RelationshipService.THREAD_CLOSED_KEY]
        )
        with self.assertRaisesRegex(ValueError, "is closed"):
            RelationshipService.continue_thread(
                from_leaf=self.leaves[1],
                to_leaf=self.leaves[2],
                created_by=self.author,
                position=2,
                thread_id=thread_id,
            )


class CommonsPresenceLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        RelationshipType.objects.get_or_create(
            slug="presence",
            defaults={
                "label": "Present at",
                "domain": RelationshipType.DOMAIN_COMMONS,
                "uses_lifecycle": True,
            },
        )

    def setUp(self):
        self.author = User.objects.create_user(
            username="commons-presence-author",
            email="commons-presence@example.com",
            password="testpass123",
        )
        self.attendee = User.objects.create_user(
            username="commons-presence-attendee",
            email="commons-attendee@example.com",
            password="testpass123",
        )

    def test_presence_can_be_acknowledged(self):
        relationship_type = RelationshipType.objects.get(slug="presence")
        self.assertEqual(relationship_type.domain, RelationshipType.DOMAIN_COMMONS)
        self.assertTrue(relationship_type.uses_lifecycle)

        relationship = RelationshipService.create_relationship(
            type_slug="presence",
            source=Leaf.objects.create(author=self.author),
            target=self.attendee,
            created_by=self.author,
        )
        self.assertEqual(relationship.lifecycle, Relationship.LIFECYCLE_AUTHORED)

        acknowledged = RelationshipService.acknowledge_relationship(
            relationship_id=relationship.pk,
            acknowledged_by=self.attendee,
        )

        self.assertEqual(
            acknowledged.lifecycle, Relationship.LIFECYCLE_ACKNOWLEDGED
        )
        self.assertEqual(
            acknowledged.metadata["acknowledged_by"], str(self.attendee.pk)
        )
        self.assertIn("acknowledged_at", acknowledged.metadata)
