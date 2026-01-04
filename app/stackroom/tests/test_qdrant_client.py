"""
Tests for Qdrant Client Wrapper

Tests the contract-compliant Qdrant operations.
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from uuid import uuid4

from stackroom.services.qdrant_client import (
    QdrantClientWrapper,
    build_payload_from_embedding,
    get_qdrant_client,
)
from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
)
import hashlib


class QdrantClientTests(TestCase):
    """Test Qdrant client wrapper"""

    def setUp(self):
        """Set up test fixtures"""
        # Create test data for payload building
        self.library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant",
            name="Test Library",
        )

        self.source_file = SourceFile.objects.create(
            library=self.library,
            origin="upload",
            path="test/test.txt",
            filename="test.txt",
            content_type="text/plain",
            size_bytes=100,
            hash_sha256="abc123" * 10,
        )

        self.artifact = Artifact.objects.create(
            source_file=self.source_file,
            artifact_uid="artifact-1",
            artifact_type="extracted_text",
            format="text/plain",
            text="Test content",
        )

        self.chunk = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="Test content",
            token_estimate=2,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 12}],
            hash_sha256=hashlib.sha256("Test content".encode()).hexdigest(),
        )

        self.embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        self.chunk_embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=hashlib.sha256("Test content".encode()).hexdigest(),
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
        )

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_ensure_collection_creates_new(self, mock_qdrant):
        """Test creating a new collection"""
        # Mock: collection doesn't exist
        mock_client = Mock()
        mock_qdrant.return_value = mock_client
        mock_client.get_collections.return_value = Mock(collections=[])

        wrapper = QdrantClientWrapper()
        created = wrapper.ensure_collection("test-collection", 768)

        # Should have created collection
        self.assertTrue(created)
        mock_client.create_collection.assert_called_once()

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_ensure_collection_exists_with_same_dimensions(self, mock_qdrant):
        """Test collection already exists with correct dimensions"""
        # Mock: collection exists
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        # Create mock collection with 'name' as regular attribute
        existing_collection = Mock()
        existing_collection.name = "test-collection"
        mock_client.get_collections.return_value = Mock(
            collections=[existing_collection]
        )

        # Mock collection info with correct dimensions
        collection_info = Mock()
        collection_info.config.params.vectors.size = 768
        mock_client.get_collection.return_value = collection_info

        wrapper = QdrantClientWrapper()
        created = wrapper.ensure_collection("test-collection", 768)

        # Should not have created collection
        self.assertFalse(created)
        mock_client.create_collection.assert_not_called()

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_ensure_collection_dimension_mismatch(self, mock_qdrant):
        """Test collection exists with wrong dimensions raises error"""
        # Mock: collection exists with different dimensions
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        # Create mock collection with 'name' as regular attribute
        existing_collection = Mock()
        existing_collection.name = "test-collection"
        mock_client.get_collections.return_value = Mock(
            collections=[existing_collection]
        )

        # Mock collection info with wrong dimensions
        collection_info = Mock()
        collection_info.config.params.vectors.size = 512  # Wrong!
        mock_client.get_collection.return_value = collection_info

        wrapper = QdrantClientWrapper()

        with self.assertRaises(ValueError) as ctx:
            wrapper.ensure_collection("test-collection", 768)

        self.assertIn("exists with 512 dimensions", str(ctx.exception))

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_upsert_point(self, mock_qdrant):
        """Test upserting a vector point"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        wrapper = QdrantClientWrapper()

        point_id = str(uuid4())
        vector = [0.1] * 768
        payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
        }

        wrapper.upsert_point("test-collection", point_id, vector, payload)

        # Should have called upsert
        mock_client.upsert.assert_called_once()
        call_args = mock_client.upsert.call_args
        self.assertEqual(call_args[1]["collection_name"], "test-collection")

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_upsert_point_rejects_text_payload(self, mock_qdrant):
        """Test payload validation rejects text content"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        wrapper = QdrantClientWrapper()

        point_id = str(uuid4())
        vector = [0.1] * 768
        payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
            "text": "This should not be here!",  # Forbidden
        }

        with self.assertRaises(ValueError) as ctx:
            wrapper.upsert_point("test-collection", point_id, vector, payload)

        self.assertIn("forbidden keys", str(ctx.exception).lower())

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_search(self, mock_qdrant):
        """Test vector search"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        # Mock search results
        hit1 = Mock()
        hit1.id = "point-1"
        hit1.score = 0.95
        hit1.payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
        }

        hit2 = Mock()
        hit2.id = "point-2"
        hit2.score = 0.87
        hit2.payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
        }

        mock_client.search.return_value = [hit1, hit2]

        wrapper = QdrantClientWrapper()
        vector = [0.1] * 768
        results = wrapper.search("test-collection", vector, limit=10)

        # Verify results
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["point_id"], "point-1")
        self.assertEqual(results[0]["score"], 0.95)
        self.assertIn("chunk_id", results[0])

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_delete_point(self, mock_qdrant):
        """Test deleting a point"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        wrapper = QdrantClientWrapper()
        wrapper.delete_point("test-collection", "point-1")

        mock_client.delete.assert_called_once()

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_collection_exists(self, mock_qdrant):
        """Test checking if collection exists"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        # Create mock collections with 'name' as regular attribute
        collection1 = Mock()
        collection1.name = "collection-1"
        collection2 = Mock()
        collection2.name = "collection-2"
        mock_client.get_collections.return_value = Mock(
            collections=[collection1, collection2]
        )

        wrapper = QdrantClientWrapper()

        self.assertTrue(wrapper.collection_exists("collection-1"))
        self.assertFalse(wrapper.collection_exists("collection-3"))

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_get_point(self, mock_qdrant):
        """Test retrieving a point by ID"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client

        # Mock retrieved point
        point = Mock()
        point.id = "point-1"
        point.vector = [0.1] * 768
        point.payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
        }
        mock_client.retrieve.return_value = [point]

        wrapper = QdrantClientWrapper()
        result = wrapper.get_point("test-collection", "point-1")

        self.assertIsNotNone(result)
        self.assertEqual(result["point_id"], "point-1")
        self.assertEqual(len(result["vector"]), 768)

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_get_point_not_found(self, mock_qdrant):
        """Test retrieving non-existent point returns None"""
        mock_client = Mock()
        mock_qdrant.return_value = mock_client
        mock_client.retrieve.return_value = []

        wrapper = QdrantClientWrapper()
        result = wrapper.get_point("test-collection", "nonexistent")

        self.assertIsNone(result)

    def test_build_payload_from_embedding(self):
        """Test building payload from ChunkEmbedding instance"""
        payload = build_payload_from_embedding(self.chunk_embedding)

        # Should contain only IDs
        self.assertIn("chunk_id", payload)
        self.assertIn("library_id", payload)
        self.assertIn("embedding_model_id", payload)

        # Should be strings
        self.assertIsInstance(payload["chunk_id"], str)
        self.assertIsInstance(payload["library_id"], str)
        self.assertIsInstance(payload["embedding_model_id"], str)

        # Should match the actual IDs
        self.assertEqual(payload["chunk_id"], str(self.chunk.id))
        self.assertEqual(payload["library_id"], str(self.library.id))
        self.assertEqual(payload["embedding_model_id"], str(self.embedding_model.id))

        # Should NOT contain text or provenance
        self.assertNotIn("text", payload)
        self.assertNotIn("content", payload)
        self.assertNotIn("spans", payload)
        self.assertNotIn("provenance", payload)

    def test_payload_validation_missing_keys(self):
        """Test payload validation catches missing required keys"""
        wrapper = QdrantClientWrapper()

        # Missing library_id
        payload = {
            "chunk_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
        }

        with self.assertRaises(ValueError) as ctx:
            wrapper._validate_payload(payload)

        self.assertIn("missing required keys", str(ctx.exception).lower())

    def test_payload_validation_forbidden_keys(self):
        """Test payload validation catches forbidden keys"""
        wrapper = QdrantClientWrapper()

        # Has forbidden 'text' key
        payload = {
            "chunk_id": str(uuid4()),
            "library_id": str(uuid4()),
            "embedding_model_id": str(uuid4()),
            "text": "This violates the contract",
        }

        with self.assertRaises(ValueError) as ctx:
            wrapper._validate_payload(payload)

        self.assertIn("forbidden keys", str(ctx.exception).lower())

    @patch("stackroom.services.qdrant_client.QdrantClient")
    def test_get_qdrant_client_singleton(self, mock_qdrant):
        """Test get_qdrant_client returns singleton"""
        # Clear any existing global client
        import stackroom.services.qdrant_client as module
        module._client = None

        client1 = get_qdrant_client()
        client2 = get_qdrant_client()

        # Should be same instance
        self.assertIs(client1, client2)
