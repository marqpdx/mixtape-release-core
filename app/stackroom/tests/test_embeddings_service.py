"""
Tests for Embedding Service Layer

Tests the orchestration of embedding operations.
"""

import hashlib
from unittest.mock import patch, Mock
from django.test import TestCase

from stackroom.services.embeddings import (
    get_or_create_embedding_model,
    backfill_chunk_embeddings,
    backfill_library_embeddings,
    get_pending_embeddings,
    get_stale_embeddings,
    mark_stale_embeddings_pending,
    get_embedding_stats,
    delete_library_embeddings,
    EmbeddingServiceError,
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


class EmbeddingServiceTests(TestCase):
    """Test embedding service layer"""

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
            text="Original content",
        )

        # Create chunks
        self.chunk1 = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="First chunk",
            token_estimate=2,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 11}],
            hash_sha256=hashlib.sha256("First chunk".encode()).hexdigest(),
        )

        self.chunk2 = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="Second chunk",
            token_estimate=2,
            order_index=1,
            source_spans=[{"char_start": 12, "char_end": 24}],
            hash_sha256=hashlib.sha256("Second chunk".encode()).hexdigest(),
        )

    def test_get_or_create_embedding_model_create(self):
        """Test creating a new EmbeddingModel"""
        model, created = get_or_create_embedding_model(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        self.assertTrue(created)
        self.assertEqual(model.name, "text-embedding-3-small")
        self.assertEqual(model.version, "1")
        self.assertEqual(model.dimensions, 1536)

    def test_get_or_create_embedding_model_get_existing(self):
        """Test getting existing EmbeddingModel"""
        # Create first
        model1, created1 = get_or_create_embedding_model(
            name="test-model",
            version="1",
            provider="openai",
            dimensions=768,
        )
        self.assertTrue(created1)

        # Get existing
        model2, created2 = get_or_create_embedding_model(
            name="test-model",
            version="1",
            provider="openai",
            dimensions=768,
        )

        self.assertFalse(created2)
        self.assertEqual(model1.id, model2.id)

    def test_get_or_create_embedding_model_dimension_mismatch(self):
        """Test dimension mismatch raises error"""
        # Create with 768 dimensions
        model1, _ = get_or_create_embedding_model(
            name="test-model",
            version="1",
            provider="openai",
            dimensions=768,
        )

        # Try to get with different dimensions
        with self.assertRaises(EmbeddingServiceError) as ctx:
            get_or_create_embedding_model(
                name="test-model",
                version="1",
                provider="openai",
                dimensions=1536,  # Different!
            )

        self.assertIn("exists with 768 dimensions", str(ctx.exception))

    @patch("stackroom.services.embeddings.get_embedding_dimensions")
    def test_get_or_create_infers_dimensions(self, mock_get_dims):
        """Test dimension inference from provider"""
        mock_get_dims.return_value = 1536

        model, created = get_or_create_embedding_model(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            # dimensions NOT provided
        )

        self.assertTrue(created)
        self.assertEqual(model.dimensions, 1536)
        mock_get_dims.assert_called_once_with("text-embedding-3-small", "openai")

    def test_backfill_chunk_embeddings(self):
        """Test backfilling ChunkEmbedding rows"""
        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Backfill
        stats = backfill_chunk_embeddings(self.library, embedding_model)

        # Should have created 2 embeddings (one per chunk)
        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["existing"], 0)

        # Verify embeddings exist
        embeddings = ChunkEmbedding.objects.filter(
            library=self.library,
            embedding_model=embedding_model,
        )
        self.assertEqual(embeddings.count(), 2)

        # All should be PENDING
        self.assertTrue(all(e.status == EmbeddingStatus.PENDING for e in embeddings))

    def test_backfill_idempotent(self):
        """Test backfill is idempotent"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # First backfill
        stats1 = backfill_chunk_embeddings(self.library, embedding_model)
        self.assertEqual(stats1["created"], 2)

        # Second backfill - should find existing
        stats2 = backfill_chunk_embeddings(self.library, embedding_model)
        self.assertEqual(stats2["created"], 0)
        self.assertEqual(stats2["existing"], 2)

        # Still only 2 total
        total = ChunkEmbedding.objects.filter(
            library=self.library,
            embedding_model=embedding_model,
        ).count()
        self.assertEqual(total, 2)

    @patch("stackroom.services.embeddings.get_qdrant_client")
    @patch("stackroom.services.embeddings.get_embedding_dimensions")
    def test_backfill_library_embeddings(self, mock_get_dims, mock_get_client):
        """Test high-level library backfill"""
        mock_get_dims.return_value = 1536

        # Mock Qdrant client
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        stats = backfill_library_embeddings(
            library_id=self.library.id,
            model_name="text-embedding-3-small",
            model_version="1",
            provider="openai",
        )

        # Should have created embeddings
        self.assertEqual(stats["created"], 2)
        self.assertIn("collection", stats)

        # Should have ensured collection exists
        mock_client.ensure_collection.assert_called_once()

    def test_get_pending_embeddings(self):
        """Test getting pending embeddings"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create embeddings with different statuses
        text_hash1 = hashlib.sha256(self.chunk1.text.encode()).hexdigest()
        text_hash2 = hashlib.sha256(self.chunk2.text.encode()).hexdigest()

        ChunkEmbedding.objects.create(
            chunk=self.chunk1,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash1,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk1.id),
            status=EmbeddingStatus.PENDING,
        )

        ChunkEmbedding.objects.create(
            chunk=self.chunk2,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash2,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk2.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Get pending only
        pending = get_pending_embeddings(library=self.library)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].chunk_id, self.chunk1.id)

    def test_get_stale_embeddings(self):
        """Test detecting stale embeddings"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create embedding with CURRENT chunk text
        current_text = self.chunk1.text  # "First chunk"
        text_hash = hashlib.sha256(current_text.encode()).hexdigest()

        embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk1,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk1.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Chunk text hasn't changed yet - should not be stale
        stale = get_stale_embeddings(library=self.library)
        self.assertEqual(len(stale), 0)

        # Change chunk text
        self.chunk1.text = "Modified text"
        self.chunk1.save()

        # Now should be stale
        stale = get_stale_embeddings(library=self.library)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].id, embedding.id)

    def test_mark_stale_embeddings_pending(self):
        """Test marking stale embeddings as PENDING"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create embedding
        text_hash = hashlib.sha256("Old text".encode()).hexdigest()

        embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk1,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk1.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Change chunk text to make it stale
        self.chunk1.text = "New text"
        self.chunk1.save()

        # Mark stale as pending
        count = mark_stale_embeddings_pending(library=self.library)

        self.assertEqual(count, 1)

        # Verify status and hash updated
        embedding.refresh_from_db()
        self.assertEqual(embedding.status, EmbeddingStatus.PENDING)
        self.assertEqual(
            embedding.embedded_text_hash,
            hashlib.sha256("New text".encode()).hexdigest(),
        )

    def test_get_embedding_stats(self):
        """Test getting embedding statistics"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create embeddings with different statuses
        text_hash1 = hashlib.sha256(self.chunk1.text.encode()).hexdigest()
        text_hash2 = hashlib.sha256(self.chunk2.text.encode()).hexdigest()

        ChunkEmbedding.objects.create(
            chunk=self.chunk1,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash1,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk1.id),
            status=EmbeddingStatus.PENDING,
        )

        ChunkEmbedding.objects.create(
            chunk=self.chunk2,
            embedding_model=embedding_model,
            library=self.library,
            embedded_text_hash=text_hash2,
            qdrant_collection="test",
            qdrant_point_id=str(self.chunk2.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Get stats
        stats = get_embedding_stats(library=self.library)

        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["pending"], 1)
        self.assertEqual(stats["complete"], 1)
        self.assertEqual(stats["failed"], 0)

    @patch("stackroom.services.embeddings.get_qdrant_client")
    def test_delete_library_embeddings(self, mock_get_client):
        """Test deleting library embeddings"""
        # Mock Qdrant client
        mock_client = Mock()
        mock_client.collection_exists.return_value = True
        mock_get_client.return_value = mock_client

        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create embeddings
        backfill_chunk_embeddings(self.library, embedding_model)

        # Verify created
        self.assertEqual(
            ChunkEmbedding.objects.filter(library=self.library).count(), 2
        )

        # Delete
        count = delete_library_embeddings(self.library, delete_from_qdrant=True)

        self.assertEqual(count, 2)

        # Verify deleted from Django
        self.assertEqual(
            ChunkEmbedding.objects.filter(library=self.library).count(), 0
        )

        # Verify Qdrant collection deleted
        mock_client.delete_collection.assert_called()

    def test_backfill_library_not_found(self):
        """Test backfill with non-existent library raises error"""
        with self.assertRaises(EmbeddingServiceError) as ctx:
            backfill_library_embeddings(
                library_id="00000000-0000-0000-0000-000000000000",
                model_name="test",
                model_version="1",
            )

        self.assertIn("not found", str(ctx.exception))

    def test_get_pending_embeddings_with_limit(self):
        """Test getting pending embeddings with limit"""
        embedding_model = EmbeddingModel.objects.create(
            name="test-model",
            version="1",
            provider="test",
            dimensions=768,
        )

        # Create 2 pending embeddings
        backfill_chunk_embeddings(self.library, embedding_model)

        # Get with limit=1
        pending = get_pending_embeddings(library=self.library, limit=1)

        self.assertEqual(len(pending), 1)

    def test_get_pending_embeddings_filters_by_model(self):
        """Test filtering pending by embedding model"""
        model1 = EmbeddingModel.objects.create(
            name="model-1", version="1", provider="test", dimensions=768
        )
        model2 = EmbeddingModel.objects.create(
            name="model-2", version="1", provider="test", dimensions=1536
        )

        # Backfill with both models
        backfill_chunk_embeddings(self.library, model1)
        backfill_chunk_embeddings(self.library, model2)

        # Get pending for model1 only
        pending = get_pending_embeddings(
            library=self.library, embedding_model=model1
        )

        self.assertEqual(len(pending), 2)
        self.assertTrue(all(e.embedding_model_id == model1.id for e in pending))
