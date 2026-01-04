"""
Tests for Batch Embedding Functionality

Tests the batch processing improvements:
- Batch chunking in embed_texts()
- Exponential backoff on rate limits
- Batch Celery task (embed_pending_batch)
"""

import hashlib
from unittest.mock import patch, Mock
from django.test import TestCase
from django.contrib.auth import get_user_model

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
)
from stackroom.services.embedding_provider import (
    embed_texts,
    RateLimitError,
    OPENAI_MAX_BATCH_SIZE,
    SENTENCE_TRANSFORMERS_DEFAULT_BATCH_SIZE,
)
from stackroom.tasks.embeddings import embed_pending_batch


class BatchEmbeddingTests(TestCase):
    """Test batch embedding functionality"""

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

    @patch("stackroom.services.embedding_provider._embed_openai")
    def test_batch_chunking_openai(self, mock_embed_openai):
        """Test that large inputs are automatically chunked for OpenAI"""
        # Create 3000 texts (exceeds 2048 limit)
        num_texts = 3000
        texts = [f"Text {i}" for i in range(num_texts)]

        # Mock returns correctly sized vectors based on input
        def side_effect(texts, **kwargs):
            return [[0.1] * 1536 for _ in texts]

        mock_embed_openai.side_effect = side_effect

        # Call embed_texts
        vectors = embed_texts(
            texts=texts,
            embedding_model=self.embedding_model,
        )

        # Verify chunking occurred
        # Should be called twice: ceil(3000 / 2048) = 2 batches
        self.assertEqual(mock_embed_openai.call_count, 2)

        # First batch: 2048 texts
        first_call_texts = mock_embed_openai.call_args_list[0][0][0]
        self.assertEqual(len(first_call_texts), 2048)

        # Second batch: 952 texts
        second_call_texts = mock_embed_openai.call_args_list[1][0][0]
        self.assertEqual(len(second_call_texts), 952)

        # Total vectors returned
        self.assertEqual(len(vectors), num_texts)

    @patch("stackroom.services.embedding_provider._embed_sentence_transformers")
    def test_batch_chunking_sentence_transformers(self, mock_embed_st):
        """Test that large inputs are chunked for sentence-transformers"""
        # Create model for sentence-transformers
        st_model = EmbeddingModel.objects.create(
            name="all-MiniLM-L6-v2",
            version="1",
            provider="sentence-transformers",
            dimensions=384,
        )

        # Create 500 texts (exceeds 128 default batch size)
        num_texts = 500
        texts = [f"Text {i}" for i in range(num_texts)]

        # Mock returns correctly sized vectors based on input
        def side_effect(texts, **kwargs):
            return [[0.1] * 384 for _ in texts]

        mock_embed_st.side_effect = side_effect

        # Call embed_texts
        vectors = embed_texts(
            texts=texts,
            embedding_model=st_model,
        )

        # Verify chunking occurred
        # Should be called: ceil(500 / 128) = 4 batches
        self.assertEqual(mock_embed_st.call_count, 4)

        # Total vectors returned
        self.assertEqual(len(vectors), num_texts)

    def test_exponential_backoff_constants(self):
        """Test that exponential backoff constants are defined correctly"""
        from stackroom.services.embedding_provider import (
            MAX_RETRIES,
            INITIAL_RETRY_DELAY,
            MAX_RETRY_DELAY,
        )

        # Verify constants exist and have reasonable values
        self.assertGreater(MAX_RETRIES, 0)
        self.assertGreater(INITIAL_RETRY_DELAY, 0)
        self.assertGreater(MAX_RETRY_DELAY, INITIAL_RETRY_DELAY)

        # Max retries should be 3-5 (industry standard)
        self.assertIn(MAX_RETRIES, [3, 4, 5])

        # Initial delay should be 1-2 seconds
        self.assertLessEqual(INITIAL_RETRY_DELAY, 2.0)

        # Max delay should be reasonable (< 2 minutes)
        self.assertLessEqual(MAX_RETRY_DELAY, 120.0)

    def test_rate_limit_error_exception_exists(self):
        """Test that RateLimitError exception is defined"""
        # Should be importable
        self.assertIsNotNone(RateLimitError)

        # Should inherit from EmbeddingProviderError
        from stackroom.services.embedding_provider import EmbeddingProviderError
        self.assertTrue(issubclass(RateLimitError, EmbeddingProviderError))

    def test_custom_batch_size_override(self):
        """Test that custom batch_size parameter is respected"""
        with patch("stackroom.services.embedding_provider._embed_openai") as mock_embed:
            mock_embed.return_value = [[0.1] * 1536]

            # Create 100 texts with batch_size=50
            texts = [f"Text {i}" for i in range(100)]

            vectors = embed_texts(
                texts=texts,
                embedding_model=self.embedding_model,
                batch_size=50,
            )

            # Should be called twice (100 / 50 = 2)
            self.assertEqual(mock_embed.call_count, 2)

            # Each batch should have 50 texts
            self.assertEqual(len(mock_embed.call_args_list[0][0][0]), 50)
            self.assertEqual(len(mock_embed.call_args_list[1][0][0]), 50)

    @patch("stackroom.tasks.embeddings.embed_texts")
    @patch("stackroom.tasks.embeddings.get_qdrant_client")
    def test_batch_celery_task(self, mock_get_qdrant, mock_embed_texts):
        """Test embed_pending_batch Celery task"""
        # Create chunks
        chunks = []
        chunk_embeddings = []

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
            chunks.append(chunk)

            # Create ChunkEmbedding
            ce = ChunkEmbedding.objects.create(
                chunk=chunk,
                library=self.library,
                embedding_model=self.embedding_model,
                embedded_text_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
                qdrant_collection=f"test-collection",
                qdrant_point_id=str(chunk.id),
                status="pending",
            )
            chunk_embeddings.append(ce)

        # Mock embedding provider
        mock_embed_texts.return_value = [[0.1] * 1536] * 10

        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_get_qdrant.return_value = mock_qdrant

        # Run batch task
        result = embed_pending_batch(
            library_id=str(self.library.id),
            embedding_model_id=str(self.embedding_model.id),
            batch_size=500,
        )

        # Verify results
        self.assertEqual(result["success"], 10)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)

        # Verify embed_texts was called ONCE with all texts
        self.assertEqual(mock_embed_texts.call_count, 1)
        call_texts = mock_embed_texts.call_args[1]["texts"]
        self.assertEqual(len(call_texts), 10)

        # Verify all chunk embeddings marked as complete
        for ce in chunk_embeddings:
            ce.refresh_from_db()
            self.assertEqual(ce.status, "complete")


class BatchEmbeddingConstantsTests(TestCase):
    """Test batch embedding constants are correct"""

    def test_openai_batch_size_constant(self):
        """Verify OpenAI batch size matches API limit"""
        # OpenAI API supports up to 2048 texts per call
        self.assertEqual(OPENAI_MAX_BATCH_SIZE, 2048)

    def test_sentence_transformers_batch_size(self):
        """Verify sentence-transformers batch size is reasonable"""
        # Should be reasonable for CPU/GPU processing
        self.assertGreater(SENTENCE_TRANSFORMERS_DEFAULT_BATCH_SIZE, 0)
        self.assertLess(SENTENCE_TRANSFORMERS_DEFAULT_BATCH_SIZE, 1000)
