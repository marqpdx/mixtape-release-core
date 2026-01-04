"""
Tests for Retrieval API

Tests the contract-compliant semantic retrieval endpoint.
"""

import hashlib
from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
# from django.urls import reverse  # Not using reverse since no namespace
from rest_framework.test import APIClient, force_authenticate
from rest_framework import status
from django.contrib.auth import get_user_model

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
)


@patch("stackroom.api.permissions.HasStackroomIRScope.has_permission", return_value=True)
class RetrievalAPITests(TestCase):
    """Test retrieval API endpoint"""

    def setUp(self):
        """Set up test fixtures"""
        self.client = APIClient()

        # Create test user and authenticate
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.force_authenticate(user=self.user)

        # Create library
        self.library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant",
            name="Test Library",
        )

        # Create source file
        self.source_file = SourceFile.objects.create(
            library=self.library,
            origin="upload",
            path="test/doc.txt",
            filename="doc.txt",
            content_type="text/plain",
            size_bytes=100,
            hash_sha256="abc123" * 10,
        )

        # Create artifact
        self.artifact = Artifact.objects.create(
            source_file=self.source_file,
            artifact_uid="artifact-1",
            artifact_type="extracted_text",
            format="text/plain",
            text="Full document text",
        )

        # Create chunks
        self.chunk1 = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="Python is a programming language",
            token_estimate=6,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 33}],
            hash_sha256=hashlib.sha256("Python is a programming language".encode()).hexdigest(),
        )

        self.chunk2 = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="JavaScript is used for web development",
            token_estimate=6,
            order_index=1,
            source_spans=[{"char_start": 34, "char_end": 72}],
            hash_sha256=hashlib.sha256("JavaScript is used for web development".encode()).hexdigest(),
        )

        # Create embedding model
        self.embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_retrieve_success(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test successful retrieval"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            }
        ]

        # Make request
        url = "/api/stackroom/retrieve"  # Adjust based on your URL config
        data = {
            "query": "python programming",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        # Note: You may need to add authentication
        response = self.client.post(url, data, format="json")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["query"], "python programming")
        self.assertEqual(len(response.data["results"]), 1)

        result = response.data["results"][0]
        self.assertEqual(str(result["chunk_id"]), str(self.chunk1.id))
        self.assertEqual(result["text"], "Python is a programming language")
        self.assertEqual(result["score"], 0.95)
        self.assertEqual(str(result["source_file_id"]), str(self.source_file.id))

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_retrieve_model_not_found(self, mock_get_client, mock_permission):
        """Test retrieval with non-existent model"""
        url = "/api/stackroom/retrieve"
        data = {
            "query": "test",
            "library_id": str(self.library.id),
            "model_name": "nonexistent-model",
            "model_version": "999",
            "limit": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("No results yet", response.data["detail"])
        self.assertEqual(response.data["error"], "model_not_found")

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_retrieve_collection_not_found(self, mock_get_client, mock_permission):
        """Test retrieval when collection doesn't exist"""
        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = False

        url = "/api/stackroom/retrieve"
        data = {
            "query": "test",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("No indexed content", response.data["detail"])
        self.assertEqual(response.data["error"], "no_embeddings")

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_retrieve_library_isolation(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test that library isolation is enforced"""
        # Create second library
        library2 = Library.objects.create(
            tenant_type="group",
            tenant_id="other-tenant",
            name="Other Library",
        )

        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return chunk from OTHER library
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),  # From library1
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            }
        ]

        # Query library2 - should NOT return chunk1
        url = "/api/stackroom/retrieve"
        data = {
            "query": "test",
            "library_id": str(library2.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        response = self.client.post(url, data, format="json")

        # Should succeed but return no results (library isolation)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_retrieve_with_score_threshold(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test retrieval with score threshold"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return multiple results
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
            {
                "point_id": str(self.chunk2.id),
                "chunk_id": str(self.chunk2.id),
                "score": 0.75,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
        ]

        url = "/api/stackroom/retrieve"
        data = {
            "query": "test",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
            "score_threshold": 0.8,
        }

        response = self.client.post(url, data, format="json")

        # Verify threshold passed to Qdrant
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args[1]
        self.assertEqual(call_kwargs["score_threshold"], 0.8)

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_retrieve_empty_results(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test retrieval with no results"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return empty results
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = []

        url = "/api/stackroom/retrieve"
        data = {
            "query": "nonexistent query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_retrieve_maintains_qdrant_ordering(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test that results maintain Qdrant ordering"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return results in specific order
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk2.id),
                "chunk_id": str(self.chunk2.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.85,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
        ]

        url = "/api/stackroom/retrieve"
        data = {
            "query": "test",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 10,
        }

        response = self.client.post(url, data, format="json")

        # Verify ordering matches Qdrant
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(str(response.data["results"][0]["chunk_id"]), str(self.chunk2.id))
        self.assertEqual(str(response.data["results"][1]["chunk_id"]), str(self.chunk1.id))

    def test_retrieve_validation(self, mock_permission):
        """Test request validation"""
        url = "/api/stackroom/retrieve"

        # Missing required fields
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid limit
        data = {
            "query": "test",
            "library_id": str(self.library.id),
            "limit": 1000,  # Too high
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_query_length_validation(self, mock_permission):
        """Test query length validation (min 3, max 500 chars)"""
        url = "/api/stackroom/retrieve"

        # Query too short (< 3 chars)
        data = {
            "query": "ab",  # Only 2 characters
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Query too long (> 500 chars)
        data = {
            "query": "a" * 501,  # 501 characters
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_filter_by_artifact_type(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test filtering by artifact type"""
        # Create second artifact with different type
        artifact2 = Artifact.objects.create(
            source_file=self.source_file,
            artifact_uid="artifact-2",
            artifact_type="normalized_markdown",
            format="text/markdown",
            text="Markdown content",
        )

        chunk3 = Chunk.objects.create(
            artifact=artifact2,
            chunk_strategy="test",
            text="Markdown chunk content",
            token_estimate=3,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 21}],
            hash_sha256=hashlib.sha256("Markdown chunk content".encode()).hexdigest(),
        )

        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return both chunks
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
            {
                "point_id": str(chunk3.id),
                "chunk_id": str(chunk3.id),
                "score": 0.90,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
        ]

        # Query with artifact_type filter
        url = "/api/stackroom/retrieve"
        data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "artifact_types": ["normalized_markdown"],
        }

        response = self.client.post(url, data, format="json")

        # Should only return chunk3 (markdown artifact)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(str(response.data["results"][0]["chunk_id"]), str(chunk3.id))
        self.assertEqual(response.data["results"][0]["artifact_type"], "normalized_markdown")

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_filter_by_source_file_ids(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test filtering by source file IDs"""
        # Create second source file and chunk
        source_file2 = SourceFile.objects.create(
            library=self.library,
            origin="upload",
            path="test/doc2.txt",
            filename="doc2.txt",
            content_type="text/plain",
            size_bytes=100,
            hash_sha256="def456" * 10,
        )

        artifact2 = Artifact.objects.create(
            source_file=source_file2,
            artifact_uid="artifact-3",
            artifact_type="extracted_text",
            format="text/plain",
            text="Second document",
        )

        chunk3 = Chunk.objects.create(
            artifact=artifact2,
            chunk_strategy="test",
            text="Content from second file",
            token_estimate=4,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 24}],
            hash_sha256=hashlib.sha256("Content from second file".encode()).hexdigest(),
        )

        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant to return both chunks
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
            {
                "point_id": str(chunk3.id),
                "chunk_id": str(chunk3.id),
                "score": 0.90,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            },
        ]

        # Query with source_file_ids filter
        url = "/api/stackroom/retrieve"
        data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "source_file_ids": [str(source_file2.id)],
        }

        response = self.client.post(url, data, format="json")

        # Should only return chunk3 (from source_file2)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(str(response.data["results"][0]["chunk_id"]), str(chunk3.id))
        self.assertEqual(str(response.data["results"][0]["source_file_id"]), str(source_file2.id))

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_timing_metrics_in_response(self, mock_embed_texts, mock_get_client, mock_permission):
        """Test that timing metrics are included in response"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            }
        ]

        url = "/api/stackroom/retrieve"
        data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
        }

        response = self.client.post(url, data, format="json")

        # Verify timing metrics are present
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("timing", response.data)

        timing = response.data["timing"]
        self.assertIn("embed_ms", timing)
        self.assertIn("qdrant_ms", timing)
        self.assertIn("resolve_ms", timing)
        self.assertIn("total_ms", timing)

        # Verify all timing values are numeric
        self.assertIsInstance(timing["embed_ms"], (int, float))
        self.assertIsInstance(timing["qdrant_ms"], (int, float))
        self.assertIsInstance(timing["resolve_ms"], (int, float))
        self.assertIsInstance(timing["total_ms"], (int, float))

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_error_response_format(self, mock_get_client, mock_permission):
        """Test improved error response format with error codes"""
        url = "/api/stackroom/retrieve"

        # Test model not found error
        data = {
            "query": "test query",
            "library_id": str(self.library.id),
            "model_name": "nonexistent",
            "model_version": "999",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn("error", response.data)
        self.assertEqual(response.data["error"], "model_not_found")
        self.assertIn("detail", response.data)

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("stackroom.tasks.retrieval.log_query_async.delay")
    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("stackroom.services.embedding_provider.embed_texts")
    def test_query_logging(self, mock_embed_texts, mock_get_client, mock_log_task, mock_permission):
        """Test that queries are logged asynchronously"""
        # Mock embedding
        mock_embed_texts.return_value = [[0.1] * 1536]

        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.collection_exists.return_value = True
        mock_client.search.return_value = [
            {
                "point_id": str(self.chunk1.id),
                "chunk_id": str(self.chunk1.id),
                "score": 0.95,
                "library_id": str(self.library.id),
                "embedding_model_id": str(self.embedding_model.id),
            }
        ]

        url = "/api/stackroom/retrieve"
        data = {
            "query": "test query for logging",
            "library_id": str(self.library.id),
            "model_name": "text-embedding-3-small",
            "model_version": "1",
            "limit": 5,
        }

        response = self.client.post(url, data, format="json")

        # Verify response is successful
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify log_query_async task was called
        mock_log_task.assert_called_once()
        call_kwargs = mock_log_task.call_args[1]

        self.assertEqual(call_kwargs["library_id"], str(self.library.id))
        self.assertEqual(call_kwargs["query_text"], "test query for logging")
        self.assertEqual(call_kwargs["embedding_model_id"], str(self.embedding_model.id))
        self.assertEqual(call_kwargs["limit"], 5)
        self.assertEqual(call_kwargs["result_count"], 1)
        self.assertIn("timing", call_kwargs)
