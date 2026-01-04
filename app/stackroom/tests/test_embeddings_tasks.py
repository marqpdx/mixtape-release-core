"""
Tests for Embedding Celery Tasks

Tests the async task execution for embeddings.
"""

import hashlib
from unittest.mock import patch, Mock, call
from django.test import TestCase, override_settings

from stackroom.tasks.embeddings import (
    embed_library,
    embed_chunk_embedding,
    embed_pending_batch,
)
from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
    EmbeddingStatus,
)


class EmbeddingTasksTests(TestCase):
    """Test embedding Celery tasks"""

    def setUp(self):
        """Set up test fixtures"""
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
            path="test/test.txt",
            filename="test.txt",
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
            text="Test content",
        )

        # Create chunk
        self.chunk = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="Test chunk text",
            token_estimate=3,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 15}],
            hash_sha256=hashlib.sha256("Test chunk text".encode()).hexdigest(),
        )

    @patch("stackroom.tasks.embeddings.embed_chunk_embedding.delay")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    @patch("stackroom.services.embeddings.get_embedding_dimensions")
    def test_embed_library(
        self, mock_get_dims, mock_get_client, mock_embed_chunk_task
    ):
        """Test embed_library task"""
        mock_get_dims.return_value = 1536

        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        # Run task
        result = embed_library(
            library_id=str(self.library.id),
            model_name="text-embedding-3-small",
            model_version="1",
            provider="openai",
        )

        # Verify results
        self.assertEqual(result["created"], 1)  # 1 chunk
        self.assertEqual(result["enqueued"], 1)  # 1 pending embedding
        self.assertIn("collection", result)

        # Verify Qdrant collection created
        mock_client.ensure_collection.assert_called_once()

        # Verify chunk task enqueued
        mock_embed_chunk_task.assert_called_once()

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("openai.OpenAI")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    def test_embed_chunk_embedding_success(self, mock_get_client, mock_openai_class):
        """Test successful chunk embedding"""
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # Create chunk embedding
        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()
        chunk_embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
            status=EmbeddingStatus.PENDING,
        )

        # Mock OpenAI response
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_item = Mock()
        mock_item.embedding = [0.1] * 1536
        mock_response.data = [mock_item]
        mock_client.embeddings.create.return_value = mock_response

        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_client.return_value = mock_qdrant

        # Run task
        result = embed_chunk_embedding(chunk_embedding_id=str(chunk_embedding.id))

        # Verify result
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunk_embedding_id"], str(chunk_embedding.id))

        # Verify embedding marked as complete
        chunk_embedding.refresh_from_db()
        self.assertEqual(chunk_embedding.status, EmbeddingStatus.COMPLETE)
        self.assertIsNotNone(chunk_embedding.completed_at)

        # Verify upserted to Qdrant
        mock_qdrant.upsert_point.assert_called_once()

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("openai.OpenAI")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    def test_embed_chunk_embedding_idempotent(
        self, mock_get_client, mock_openai_class
    ):
        """Test embedding task is idempotent"""
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # Create COMPLETED chunk embedding
        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()
        chunk_embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
            status=EmbeddingStatus.COMPLETE,  # Already complete
        )

        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_client.return_value = mock_qdrant

        # Run task
        result = embed_chunk_embedding(chunk_embedding_id=str(chunk_embedding.id))

        # Should return early
        self.assertEqual(result["status"], "already_complete")

        # Should NOT call OpenAI or Qdrant
        mock_openai_class.assert_not_called()
        mock_qdrant.upsert_point.assert_not_called()

    @override_settings(OPENAI_API_KEY="test-key")
    @patch("openai.OpenAI")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    def test_embed_chunk_embedding_failure(self, mock_get_client, mock_openai_class):
        """Test embedding task failure handling"""
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # Create chunk embedding
        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()
        chunk_embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
            status=EmbeddingStatus.PENDING,
        )

        # Mock OpenAI to raise error
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.embeddings.create.side_effect = Exception("API error")

        # Mock task to not actually retry
        with patch.object(
            embed_chunk_embedding, "retry", side_effect=Exception("API error")
        ):
            # Run task - should raise and mark as failed
            with self.assertRaises(Exception):
                embed_chunk_embedding(chunk_embedding_id=str(chunk_embedding.id))

        # Verify embedding marked as failed
        chunk_embedding.refresh_from_db()
        self.assertEqual(chunk_embedding.status, EmbeddingStatus.FAILED)
        self.assertEqual(chunk_embedding.error_code, "EmbeddingProviderError")
        self.assertIn("API error", chunk_embedding.error_detail)

    def test_embed_chunk_embedding_not_found(self):
        """Test task with non-existent chunk embedding"""
        fake_id = "99999"  # Non-existent integer ID

        result = embed_chunk_embedding(chunk_embedding_id=fake_id)

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["chunk_embedding_id"], fake_id)

    @patch("stackroom.tasks.embeddings.embed_texts")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    @patch("stackroom.tasks.embeddings.embed_chunk_embedding.delay")
    def test_embed_pending_batch(self, mock_embed_chunk_task, mock_get_qdrant, mock_embed_texts):
        """Test enqueuing batch of pending embeddings"""
        # Mock embed_texts to return correct number of vectors
        def embed_side_effect(texts, **kwargs):
            return [[0.1] * 768 for _ in texts]
        mock_embed_texts.side_effect = embed_side_effect

        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_qdrant.return_value = mock_qdrant
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create 3 pending embeddings
        for i in range(3):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk {i}",
                token_estimate=2,
                order_index=i,
                source_spans=[{"char_start": 0, "char_end": 10}],
                hash_sha256=hashlib.sha256(f"Chunk {i}".encode()).hexdigest(),
            )

            text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()
            ChunkEmbedding.objects.create(
                chunk=chunk,
                embedding_model=embedding_model,
                library=self.library,
                embedded_text_hash=text_hash,
                qdrant_collection="test-collection",
                qdrant_point_id=str(chunk.id),
                status=EmbeddingStatus.PENDING,
            )

        # Run batch task
        result = embed_pending_batch(
            library_id=str(self.library.id),
            embedding_model_id=str(embedding_model.id),
            batch_size=10,
        )

        # Should have processed 3 (new batch behavior processes directly)
        self.assertEqual(result["success"], 3)
        self.assertEqual(result["failed"], 0)
        # mock_embed_chunk_task is NOT called - batch task processes directly now
        self.assertEqual(mock_embed_chunk_task.call_count, 0)

    @patch("stackroom.tasks.embeddings.embed_texts")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    @patch("stackroom.tasks.embeddings.embed_chunk_embedding.delay")
    def test_embed_pending_batch_with_limit(self, mock_embed_chunk_task, mock_get_qdrant, mock_embed_texts):
        """Test batch task respects limit"""
        # Mock embed_texts to return correct number of vectors
        def embed_side_effect(texts, **kwargs):
            return [[0.1] * 768 for _ in texts]
        mock_embed_texts.side_effect = embed_side_effect

        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_qdrant.return_value = mock_qdrant
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create 5 pending embeddings
        for i in range(5):
            chunk = Chunk.objects.create(
                artifact=self.artifact,
                chunk_strategy="test",
                text=f"Chunk {i}",
                token_estimate=2,
                order_index=i,
                source_spans=[{"char_start": 0, "char_end": 10}],
                hash_sha256=hashlib.sha256(f"Chunk {i}".encode()).hexdigest(),
            )

            text_hash = hashlib.sha256(chunk.text.encode()).hexdigest()
            ChunkEmbedding.objects.create(
                chunk=chunk,
                embedding_model=embedding_model,
                library=self.library,
                embedded_text_hash=text_hash,
                qdrant_collection="test-collection",
                qdrant_point_id=str(chunk.id),
                status=EmbeddingStatus.PENDING,
            )

        # Run with limit=2
        result = embed_pending_batch(
            library_id=str(self.library.id),
            embedding_model_id=str(embedding_model.id),
            batch_size=2,
        )

        # Should only process 2 (batch limit)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["failed"], 0)
        # mock_embed_chunk_task is NOT called - batch task processes directly now
        self.assertEqual(mock_embed_chunk_task.call_count, 0)
