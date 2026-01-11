# stackroom/tests/test_collection_serializers.py

from django.test import TestCase

from stackroom.api.collection_serializers import (
    CollectionUpdateSerializer,
    LibraryItemCreateSerializer,
    LibraryItemBulkReorderSerializer,
)


class CollectionUpdateSerializerTests(TestCase):
    def test_empty_body_is_valid(self):
        serializer = CollectionUpdateSerializer(data={})
        self.assertTrue(serializer.is_valid())

    def test_title_too_long(self):
        serializer = CollectionUpdateSerializer(data={"title": "x" * 256})
        self.assertFalse(serializer.is_valid())


class LibraryItemCreateSerializerTests(TestCase):
    def test_folder_path_length_limit(self):
        serializer = LibraryItemCreateSerializer(
            data={
                "content_type": "source_file",
                "content_id": "00000000-0000-0000-0000-000000000000",
                "folder_path": "a" * 500,
            }
        )
        self.assertTrue(serializer.is_valid())

        serializer = LibraryItemCreateSerializer(
            data={
                "content_type": "source_file",
                "content_id": "00000000-0000-0000-0000-000000000000",
                "folder_path": "a" * 501,
            }
        )
        self.assertFalse(serializer.is_valid())


class LibraryItemBulkReorderSerializerTests(TestCase):
    def test_requires_id_and_order_index(self):
        serializer = LibraryItemBulkReorderSerializer(data={"items": [{"id": "x"}]})
        self.assertFalse(serializer.is_valid())

        serializer = LibraryItemBulkReorderSerializer(
            data={"items": [{"order_index": 1}]}
        )
        self.assertFalse(serializer.is_valid())
