# stackroom/tests/test_collection_views.py

import hashlib
import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from groups.models.group import Group, GroupType
from groups.models.membership import GroupMembership
from stackroom.models import Library, LibraryItem, SourceFile


User = get_user_model()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _create_group(*, sponsor_user: User, title: str, slug: str) -> Group:
    group = Group(
        title=title,
        slug=slug,
        description="Test group",
        group_type=GroupType.COMMUNITY,
    )
    group.set_sponsor(sponsor_user)
    group.set_submitted_by(sponsor_user)
    group.author = sponsor_user
    group.author_name = sponsor_user.get_full_name() or sponsor_user.username
    group.save()
    return group


def _create_library(*, sponsor, submitted_by: User, title: str) -> Library:
    library = Library(title=title)
    library.set_sponsor(sponsor)
    library.set_submitted_by(submitted_by)
    library.author = submitted_by
    library.author_name = submitted_by.get_full_name() or submitted_by.username
    library.save()
    return library


class CollectionAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

        self.group = _create_group(
            sponsor_user=self.user,
            title="Test Group",
            slug="test-group",
        )
        user_ct = ContentType.objects.get_for_model(User)
        GroupMembership.objects.create(
            group=self.group,
            member_content_type=user_ct,
            member_object_id=self.user.id,
            roles=["admin", "member", "owner"],
            is_active=True,
        )

        self.group_collection = _create_library(
            sponsor=self.group,
            submitted_by=self.user,
            title="Group Collection",
        )
        self.user_collection = _create_library(
            sponsor=self.user,
            submitted_by=self.user,
            title="User Collection",
        )
        self.other_collection = _create_library(
            sponsor=self.group,
            submitted_by=self.user,
            title="Other Collection",
        )

        self.sf1 = SourceFile.objects.create(
            library=self.group_collection,
            origin="upload",
            path="docs/one.txt",
            filename="one.txt",
            content_type="text/plain",
            size_bytes=10,
            hash_sha256=_sha256_hex("one"),
            created_by=self.user,
        )
        self.sf2 = SourceFile.objects.create(
            library=self.group_collection,
            origin="upload",
            path="docs/two.txt",
            filename="two.txt",
            content_type="text/plain",
            size_bytes=20,
            hash_sha256=_sha256_hex("two"),
            created_by=self.user,
        )
        self.sf3 = SourceFile.objects.create(
            library=self.group_collection,
            origin="upload",
            path="docs/three.txt",
            filename="three.txt",
            content_type="text/plain",
            size_bytes=30,
            hash_sha256=_sha256_hex("three"),
            created_by=self.user,
        )
        self.sf4 = SourceFile.objects.create(
            library=self.group_collection,
            origin="upload",
            path="docs/four.txt",
            filename="four.txt",
            content_type="text/plain",
            size_bytes=40,
            hash_sha256=_sha256_hex("four"),
            created_by=self.user,
        )
        self.sf_other = SourceFile.objects.create(
            library=self.other_collection,
            origin="upload",
            path="docs/other.txt",
            filename="other.txt",
            content_type="text/plain",
            size_bytes=50,
            hash_sha256=_sha256_hex("other"),
            created_by=self.user,
        )

        self.item1 = LibraryItem.objects.create(
            library=self.group_collection,
            content_object=self.sf1,
            order_index=1,
            folder_path="research",
            tags=["alpha"],
            notes="note",
            is_featured=True,
        )
        self.item2 = LibraryItem.objects.create(
            library=self.group_collection,
            content_object=self.sf2,
            order_index=2,
            folder_path="research",
            tags=[],
            notes="",
            is_featured=False,
        )
        self.item_hidden = LibraryItem.objects.create(
            library=self.group_collection,
            content_object=self.sf3,
            order_index=3,
            is_hidden=True,
        )
        self.item_duplicate_source = LibraryItem.objects.create(
            library=self.group_collection,
            content_object=self.sf1,
            order_index=4,
        )
        self.item_other_collection = LibraryItem.objects.create(
            library=self.other_collection,
            content_object=self.sf_other,
            order_index=1,
        )

    def test_collection_list(self):
        response = self.client.get("/api/collections/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.group_collection.id), ids)
        self.assertIn(str(self.user_collection.id), ids)

        group_entry = next(
            item for item in response.data if item["id"] == str(self.group_collection.id)
        )
        self.assertEqual(group_entry["item_count"], 4)
        self.assertEqual(group_entry["file_count"], 4)

    def test_collection_list_filters_by_sponsor_type(self):
        response = self.client.get("/api/collections/", {"sponsor_type": "group"})
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.group_collection.id), ids)
        self.assertNotIn(str(self.user_collection.id), ids)

        response = self.client.get("/api/collections/", {"sponsor_type": "user"})
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.user_collection.id), ids)
        self.assertNotIn(str(self.group_collection.id), ids)

    def test_collection_list_filters_by_sponsor_id(self):
        response = self.client.get(
            "/api/collections/",
            {"sponsor_id": str(self.group.id)},
        )
        ids = {item["id"] for item in response.data}
        self.assertIn(str(self.group_collection.id), ids)
        self.assertNotIn(str(self.user_collection.id), ids)

    def test_collection_list_requires_auth(self):
        client = APIClient()
        response = client.get("/api/collections/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_collection_detail(self):
        response = self.client.get(f"/api/collections/{self.group_collection.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.group_collection.id))
        self.assertIn("title", response.data)
        self.assertIn("summary", response.data)
        self.assertIn("body", response.data)
        self.assertIn("author_name", response.data)
        self.assertIn("sponsor_type", response.data)
        self.assertIn("sponsor_id", response.data)
        self.assertIn("sponsor_name", response.data)
        self.assertIn("ingestion_status", response.data)
        self.assertIn("submitted_by", response.data)

    def test_collection_detail_not_found(self):
        response = self.client.get(f"/api/collections/{uuid.uuid4()}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_collection(self):
        payload = {
            "title": "Updated Title",
            "summary": "Updated summary",
            "body": "Updated body",
            "author_name": "New Author",
        }
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Title")
        self.assertEqual(response.data["summary"], "Updated summary")
        self.assertEqual(response.data["body"], "Updated body")
        self.assertEqual(response.data["author_name"], "New Author")

    def test_update_collection_empty_body(self):
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_collection_title_too_long(self):
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/",
            {"title": "x" * 256},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_available_files(self):
        response = self.client.get(
            f"/api/collections/{self.group_collection.id}/available-files/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)

        files = {item["id"]: item for item in response.data}
        self.assertTrue(files[str(self.sf1.id)]["in_collection"])
        self.assertEqual(files[str(self.sf1.id)]["item_count"], 2)
        self.assertFalse(files[str(self.sf4.id)]["in_collection"])
        self.assertEqual(files[str(self.sf4.id)]["item_count"], 0)

    def test_list_items_ordering_and_filters(self):
        response = self.client.get(
            f"/api/collections/{self.group_collection.id}/items/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)
        self.assertEqual(response.data[0]["id"], str(self.item1.id))

        response = self.client.get(
            f"/api/collections/{self.group_collection.id}/items/",
            {"folder": "research"},
        )
        self.assertEqual(len(response.data), 2)

        response = self.client.get(
            f"/api/collections/{self.group_collection.id}/items/",
            {"featured": "true"},
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], str(self.item1.id))

        response = self.client.get(
            f"/api/collections/{self.group_collection.id}/items/",
            {"hidden": "true"},
        )
        self.assertEqual(len(response.data), 4)

        item = response.data[0]
        self.assertEqual(item["content_type"], "source_file")
        self.assertIn("content", item)
        self.assertIn("id", item["content"])
        self.assertIn("filename", item["content"])

    def test_create_library_item_minimal(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {"content_type": "source_file", "content_id": str(self.sf4.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["content"]["id"], str(self.sf4.id))
        self.assertEqual(response.data["order_index"], 5)

    def test_create_library_item_all_fields(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {
                "content_type": "source_file",
                "content_id": str(self.sf4.id),
                "order_index": 10,
                "folder_path": "notes",
                "tags": ["t1", "t2"],
                "notes": "Important",
                "is_featured": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["order_index"], 10)
        self.assertEqual(response.data["folder_path"], "notes")
        self.assertEqual(response.data["tags"], ["t1", "t2"])
        self.assertEqual(response.data["notes"], "Important")
        self.assertTrue(response.data["is_featured"])

    def test_create_library_item_missing_source_file(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {"order_index": 1},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_library_item_invalid_source_file_id(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {"content_type": "source_file", "content_id": "not-a-uuid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_library_item_source_file_not_found(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {"content_type": "source_file", "content_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_library_item_source_file_wrong_library(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {"content_type": "source_file", "content_id": str(self.sf_other.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_library_item_duplicate_position(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/",
            {
                "content_type": "source_file",
                "content_id": str(self.sf1.id),
                "order_index": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_update_library_item(self):
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/items/{self.item2.id}/",
            {
                "order_index": 5,
                "folder_path": "updated",
                "tags": ["new"],
                "notes": "Updated notes",
                "is_featured": True,
                "is_hidden": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["order_index"], 5)
        self.assertEqual(response.data["folder_path"], "updated")
        self.assertEqual(response.data["tags"], ["new"])
        self.assertTrue(response.data["is_featured"])
        self.assertTrue(response.data["is_hidden"])

    def test_update_library_item_not_found(self):
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/items/{uuid.uuid4()}/",
            {"notes": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_library_item_wrong_collection(self):
        response = self.client.patch(
            f"/api/collections/{self.group_collection.id}/items/{self.item_other_collection.id}/",
            {"notes": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_library_item(self):
        response = self.client.delete(
            f"/api/collections/{self.group_collection.id}/items/{self.item2.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertTrue(SourceFile.objects.filter(id=self.sf2.id).exists())

    def test_delete_library_item_not_found(self):
        response = self.client.delete(
            f"/api/collections/{self.group_collection.id}/items/{uuid.uuid4()}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_library_item_wrong_collection(self):
        response = self.client.delete(
            f"/api/collections/{self.group_collection.id}/items/{self.item_other_collection.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_bulk_reorder(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/reorder/",
            {
                "items": [
                    {"id": str(self.item1.id), "order_index": 10},
                    {"id": str(self.item2.id), "order_index": 20},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.item1.refresh_from_db()
        self.item2.refresh_from_db()
        self.item_hidden.refresh_from_db()
        self.assertEqual(self.item1.order_index, 10)
        self.assertEqual(self.item2.order_index, 20)
        self.assertEqual(self.item_hidden.order_index, 3)

    def test_bulk_reorder_missing_items(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/reorder/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_reorder_item_missing_fields(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/reorder/",
            {"items": [{"id": str(self.item1.id)}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_reorder_item_not_found(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/reorder/",
            {"items": [{"id": str(uuid.uuid4()), "order_index": 1}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_reorder_wrong_collection(self):
        response = self.client.post(
            f"/api/collections/{self.group_collection.id}/items/reorder/",
            {"items": [{"id": str(self.item_other_collection.id), "order_index": 1}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
