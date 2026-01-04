"""
Tests for Stale Embedding Monitoring

Tests the stale embedding detection in health check endpoint:
- No embeddings (0% stale)
- All fresh embeddings (0% stale)
- Some stale embeddings (<10% threshold)
- Many stale embeddings (>10% threshold triggers warning)
"""

import hashlib
from unittest.mock import patch, Mock
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
)


class StaleEmbeddingMonitoringTests(TestCase):
    """Test stale embedding monitoring in health check"""

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

        # Create embedding model
        self.embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # API client
        self.client = APIClient()

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_no_embeddings(self, mock_get_qdrant):
        """Test health check when there are no embeddings"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")

        # Verify embedding check
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["status"], "healthy")
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 0)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 0)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 0.0)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_all_fresh_embeddings(self, mock_get_qdrant):
        """Test health check when all embeddings are fresh (0% stale)"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 10 fresh chunks with embeddings
        for i in range(10):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # Create embedding with matching hash (fresh)
            ChunkEmbedding.objects.create(
                chunk=chunk,
                library=self.library,
                embedding_model=self.embedding_model,
                embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                qdrant_collection=f"test-collection",
                qdrant_point_id=str(chunk.id),
                status="complete",
            )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")

        # Verify embedding check
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["status"], "healthy")
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 10)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 0)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 0.0)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_some_stale_embeddings_under_threshold(self, mock_get_qdrant):
        """Test health check when <10% embeddings are stale (no warning)"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 100 chunks with embeddings
        for i in range(100):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # First 5 are stale (5%), rest are fresh
            if i < 5:
                # Stale: hash doesn't match current text
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash="stale_hash_12345",  # Mismatched hash
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )
            else:
                # Fresh: hash matches
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")

        # Verify embedding check (5% stale - under 10% threshold)
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["status"], "healthy")
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 100)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 5)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 5.0)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_many_stale_embeddings_over_threshold(self, mock_get_qdrant):
        """Test health check when >10% embeddings are stale (warning)"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 100 chunks with embeddings
        for i in range(100):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # First 20 are stale (20%), rest are fresh
            if i < 20:
                # Stale: hash doesn't match current text
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash="stale_hash_12345",  # Mismatched hash
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )
            else:
                # Fresh: hash matches
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response (still 200 OK - warning doesn't degrade service)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")

        # Verify embedding check (20% stale - over 10% threshold)
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["status"], "warning")
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 100)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 20)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 20.0)
        self.assertIn("threshold: 10%", response.data["checks"]["embeddings"]["message"])

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_exactly_10_percent_stale(self, mock_get_qdrant):
        """Test health check when exactly 10% embeddings are stale (boundary)"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 100 chunks with embeddings
        for i in range(100):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # First 10 are stale (exactly 10%), rest are fresh
            if i < 10:
                # Stale: hash doesn't match current text
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash="stale_hash_12345",  # Mismatched hash
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )
            else:
                # Fresh: hash matches
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify embedding check (exactly 10% - should be healthy, not warning)
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["status"], "healthy")
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 10.0)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_pending_embeddings_not_counted(self, mock_get_qdrant):
        """Test that pending embeddings are not counted in stale check"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 10 chunks
        for i in range(10):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # First 5 are complete (all fresh)
            # Last 5 are pending (should not be counted)
            if i < 5:
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )
            else:
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="pending",  # Pending - should not be counted
                )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify only complete embeddings are counted
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 5)
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 0)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_stale_percentage_calculation(self, mock_get_qdrant):
        """Test that stale percentage is calculated correctly"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Create 33 chunks (to test rounding)
        for i in range(33):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk text {i}",
                token_estimate=5,
                order_index=i,
                source_spans=[{"char_start": i * 10, "char_end": i * 10 + 10}],
                hash_sha256=hashlib.sha256(f"Chunk text {i}".encode()).hexdigest(),
            )

            # First 5 are stale (5/33 = 15.15...)
            if i < 5:
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash="stale_hash_12345",
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )
            else:
                ChunkEmbedding.objects.create(
                    chunk=chunk,
                    library=self.library,
                    embedding_model=self.embedding_model,
                    embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                    qdrant_collection=f"test-collection",
                    qdrant_point_id=str(chunk.id),
                    status="complete",
                )

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify percentage is rounded to 2 decimal places
        self.assertIn("embeddings", response.data["checks"])
        self.assertEqual(response.data["checks"]["embeddings"]["stale_embeddings"], 5)
        self.assertEqual(response.data["checks"]["embeddings"]["total_embeddings"], 33)
        # 5/33 = 15.151515... → rounded to 15.15
        self.assertEqual(response.data["checks"]["embeddings"]["stale_percentage"], 15.15)
