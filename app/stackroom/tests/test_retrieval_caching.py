"""
Tests for Retrieval Result Caching

Tests the caching functionality in RetrieveView:
- Cache miss → full retrieval → cache stored
- Cache hit → instant response without Qdrant query
- Different queries → different cache keys
- Cache expiration after TTL
"""

import hashlib
import json
from unittest.mock import patch, Mock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
)


@patch("stackroom.api.permissions.HasStackroomIRScope.has_permission", return_value=True)
class RetrievalCachingTests(TestCase):
    """Test retrieval result caching functionality"""

    def setUp(self):
        """Set up test fixtures"""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )

        # Create library
        self.library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant",
            name="Test Library",
        )

        # Create source file
        self.source_file = SourceFile.objects.create(
            library=self.library,
            origin="test",
            path="test/doc.txt",
            filename="doc.txt",
            content_type="text/plain",
            size_bytes=100,
            hash_sha256="abc123" * 10,
            created_by=self.user,
        )

        # Create artifact
        self.artifact = Artifact.objects.create(
            source_file=self.source_file,
            artifact_uid="artifact-1",
            artifact_type="extracted_text",
            format="text/plain",
            text="Full document text",
        )

        # Create chunk
        self.chunk = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="Test chunk text",
            token_estimate=5,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 10}],
            hash_sha256=hashlib.sha256(b"Test chunk text").hexdigest(),
        )

        # Create embedding model
        self.embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # API client
        self.client = APIClient()
        # Authenticate client
        self.client.force_authenticate(user=self.user)

        # Clear cache before each test
        cache.clear()

    def tearDown(self):
        """Clear cache after each test"""
        cache.clear()

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_cache_miss_then_hit(self, mock_embed, mock_get_qdrant, mock_permission):
        """Test cache miss → full retrieval → cache stored → cache hit"""

        # Mock embedding
        mock_embed.return_value = [[0.1] * 1536]

        # Mock Qdrant search
        mock_qdrant = Mock()
        mock_qdrant.search.return_value = [
            {
                "chunk_id": str(self.chunk.id),
                "score": 0.95,
            }
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # First request (cache miss)
        request_data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        response1 = self.client.post("/api/stackroom/retrieve", request_data, format="json")

        # Verify response
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response1.data["results"]), 1)
        self.assertEqual(response1.data["results"][0]["text"], "Test chunk text")

        # Verify Qdrant was called
        self.assertEqual(mock_qdrant.search.call_count, 1)
        self.assertEqual(mock_embed.call_count, 1)

        # Second request (cache hit)
        response2 = self.client.post("/api/stackroom/retrieve", request_data, format="json")

        # Verify response is identical
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.data, response1.data)

        # Verify Qdrant was NOT called again (cached)
        self.assertEqual(mock_qdrant.search.call_count, 1)  # Still 1
        self.assertEqual(mock_embed.call_count, 1)  # Still 1

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_different_queries_different_cache_keys(
        self, mock_embed, mock_get_qdrant, mock_permission
    ):
        """Test that different queries use different cache keys"""
        mock_embed.return_value = [[0.1] * 1536]

        mock_qdrant = Mock()
        mock_qdrant.search.return_value = [
            {
                "chunk_id": str(self.chunk.id),
                "score": 0.95,
            }
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # First query
        request1 = {
            "query": "test query 1",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }
        response1 = self.client.post("/api/stackroom/retrieve", request1, format="json")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Second query (different text)
        request2 = {
            "query": "test query 2",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }
        response2 = self.client.post("/api/stackroom/retrieve", request2, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Verify Qdrant was called twice (different cache keys)
        self.assertEqual(mock_qdrant.search.call_count, 2)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_different_limits_different_cache_keys(
        self, mock_embed, mock_get_qdrant, mock_permission
    ):
        """Test that different limits use different cache keys"""
        mock_embed.return_value = [[0.1] * 1536]

        mock_qdrant = Mock()
        mock_qdrant.search.return_value = [
            {
                "chunk_id": str(self.chunk.id),
                "score": 0.95,
            }
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Same query, limit=10
        request1 = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }
        response1 = self.client.post("/api/stackroom/retrieve", request1, format="json")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # Same query, limit=20
        request2 = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 20,
        }
        response2 = self.client.post("/api/stackroom/retrieve", request2, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Verify Qdrant was called twice (different cache keys)
        self.assertEqual(mock_qdrant.search.call_count, 2)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_score_threshold_affects_cache_key(
        self, mock_embed, mock_get_qdrant, mock_permission
    ):
        """Test that score_threshold parameter affects cache key"""
        mock_embed.return_value = [[0.1] * 1536]

        mock_qdrant = Mock()
        mock_qdrant.search.return_value = [
            {
                "chunk_id": str(self.chunk.id),
                "score": 0.95,
            }
        ]
        mock_get_qdrant.return_value = mock_qdrant

        # Without score_threshold
        request1 = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }
        response1 = self.client.post("/api/stackroom/retrieve", request1, format="json")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)

        # With score_threshold
        request2 = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
            "score_threshold": 0.8,
        }
        response2 = self.client.post("/api/stackroom/retrieve", request2, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)

        # Verify Qdrant was called twice (different cache keys)
        self.assertEqual(mock_qdrant.search.call_count, 2)

    def test_cache_key_generation_consistency(self, mock_permission):
        """Test that cache key generation is consistent for same inputs"""
        from stackroom.api.views import RetrieveView

        view = RetrieveView()

        # Same data, different order
        data1 = {
            "query": "test",
            "library_id": "lib-123",
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
            "score_threshold": 0.8,
        }

        data2 = {
            "limit": 10,
            "query": "test",
            "score_threshold": 0.8,
            "library_id": "lib-123",
            "model_version": "1",
            "model_name": "text-embedding-3-small",
        }

        key1 = view._generate_cache_key(data1)
        key2 = view._generate_cache_key(data2)

        # Keys should be identical (order-independent)
        self.assertEqual(key1, key2)

        # Key should start with prefix
        self.assertTrue(key1.startswith("stackroom:retrieve:"))

        # Key should be deterministic length (prefix + 16-char hash)
        self.assertEqual(len(key1), len("stackroom:retrieve:") + 16)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    @patch("stackroom.api.views.RetrieveView.CACHE_TIMEOUT", 2)  # 2 seconds for testing
    def test_cache_expiration(self, mock_embed, mock_get_qdrant, mock_permission):
        """Test that cache expires after CACHE_TIMEOUT"""
        import time

        mock_embed.return_value = [[0.1] * 1536]

        mock_qdrant = Mock()
        mock_qdrant.search.return_value = [
            {
                "chunk_id": str(self.chunk.id),
                "score": 0.95,
            }
        ]
        mock_get_qdrant.return_value = mock_qdrant

        request_data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        # First request (cache miss)
        response1 = self.client.post("/api/stackroom/retrieve", request_data, format="json")
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_qdrant.search.call_count, 1)

        # Second request immediately (cache hit)
        response2 = self.client.post("/api/stackroom/retrieve", request_data, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_qdrant.search.call_count, 1)  # Still 1

        # Wait for cache to expire (2 seconds + buffer)
        time.sleep(3)

        # Third request (cache miss due to expiration)
        response3 = self.client.post("/api/stackroom/retrieve", request_data, format="json")
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_qdrant.search.call_count, 2)  # Called again

    def test_cache_key_includes_all_parameters(self, mock_permission):
        """Test that cache key includes all relevant parameters"""
        from stackroom.api.views import RetrieveView

        view = RetrieveView()

        data = {
            "query": "test query",
            "library_id": "lib-123",
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
            "score_threshold": 0.8,
        }

        # Generate cache key
        cache_key = view._generate_cache_key(data)

        # Verify it's a string
        self.assertIsInstance(cache_key, str)

        # Change each parameter and verify key changes
        for param in ["query", "library_id", "model_name", "model_version", "limit", "score_threshold"]:
            modified_data = data.copy()
            if param == "limit":
                modified_data[param] = 20
            elif param == "score_threshold":
                modified_data[param] = 0.9
            else:
                modified_data[param] = f"modified_{param}"

            modified_key = view._generate_cache_key(modified_data)
            self.assertNotEqual(cache_key, modified_key, f"Cache key should change when {param} changes")


class CacheTimeoutConfigurationTests(TestCase):
    """Test cache timeout configuration"""

    def test_cache_timeout_is_10_minutes(self):
        """Verify CACHE_TIMEOUT is set to 10 minutes (600 seconds)"""
        from stackroom.api.views import RetrieveView

        # Should be 600 seconds (10 minutes)
        self.assertEqual(RetrieveView.CACHE_TIMEOUT, 60 * 10)

    def test_cache_key_prefix_is_correct(self):
        """Verify CACHE_KEY_PREFIX is correctly set"""
        from stackroom.api.views import RetrieveView

        # Should start with stackroom:retrieve:
        self.assertEqual(RetrieveView.CACHE_KEY_PREFIX, "stackroom:retrieve:")
