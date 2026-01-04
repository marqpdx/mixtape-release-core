"""
Tests for Embedding Provider Interface

Tests the embedding provider abstraction layer.
"""

from unittest.mock import patch, Mock
from django.test import TestCase, override_settings
from django.conf import settings

from stackroom.services.embedding_provider import (
    embed_texts,
    get_embedding_dimensions,
    EmbeddingProviderError,
    DimensionMismatchError,
    _embed_openai,
    _embed_sentence_transformers,
)
from stackroom.models import EmbeddingModel


class EmbeddingProviderTests(TestCase):
    """Test embedding provider interface"""

    def setUp(self):
        """Set up test fixtures"""
        self.openai_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        self.st_model = EmbeddingModel.objects.create(
            name="all-MiniLM-L6-v2",
            version="1",
            provider="sentence-transformers",
            dimensions=384,
        )

    @override_settings(OPENAI_API_KEY="test-api-key")
    @patch("openai.OpenAI")
    def test_embed_openai_success(self, mock_openai_class):
        """Test successful OpenAI embedding"""
        # Mock OpenAI client
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Mock response
        mock_response = Mock()
        mock_item1 = Mock()
        mock_item1.embedding = [0.1] * 1536
        mock_item2 = Mock()
        mock_item2.embedding = [0.2] * 1536
        mock_response.data = [mock_item1, mock_item2]
        mock_client.embeddings.create.return_value = mock_response

        # Test embedding
        texts = ["Hello world", "Test text"]
        vectors = embed_texts(texts, embedding_model=self.openai_model)

        # Verify
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 1536)
        self.assertEqual(len(vectors[1]), 1536)
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=texts,
        )

    @override_settings(OPENAI_API_KEY="test-api-key")
    @patch("openai.OpenAI")
    def test_embed_openai_dimension_mismatch(self, mock_openai_class):
        """Test OpenAI embedding dimension validation"""
        # Mock OpenAI client
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Mock response with WRONG dimensions
        mock_response = Mock()
        mock_item = Mock()
        mock_item.embedding = [0.1] * 768  # Wrong! Should be 1536
        mock_response.data = [mock_item]
        mock_client.embeddings.create.return_value = mock_response

        # Test embedding - should raise DimensionMismatchError
        with self.assertRaises(DimensionMismatchError):
            embed_texts(["Test"], embedding_model=self.openai_model)

    @patch("sentence_transformers.SentenceTransformer")
    def test_embed_sentence_transformers_success(self, mock_st_class):
        """Test successful sentence-transformers embedding"""
        # Mock SentenceTransformer model
        mock_model = Mock()
        mock_st_class.return_value = mock_model

        # Mock embeddings (numpy array)
        import numpy as np

        mock_embeddings = np.array([[0.1] * 384, [0.2] * 384])
        mock_model.encode.return_value = mock_embeddings

        # Test embedding
        texts = ["Hello world", "Test text"]
        vectors = embed_texts(texts, embedding_model=self.st_model)

        # Verify
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 384)
        self.assertEqual(len(vectors[1]), 384)
        mock_model.encode.assert_called_once()

    @patch("sentence_transformers.SentenceTransformer")
    def test_embed_sentence_transformers_with_normalize(self, mock_st_class):
        """Test sentence-transformers respects normalize flag"""
        # Create model with normalize=True
        normalized_model = EmbeddingModel.objects.create(
            name="all-MiniLM-L6-v2",
            version="2",
            provider="sentence-transformers",
            dimensions=384,
            normalize=True,
        )

        # Mock SentenceTransformer model
        mock_model = Mock()
        mock_st_class.return_value = mock_model

        import numpy as np

        mock_embeddings = np.array([[0.1] * 384])
        mock_model.encode.return_value = mock_embeddings

        # Test embedding
        texts = ["Test"]
        vectors = embed_texts(texts, embedding_model=normalized_model)

        # Verify normalize_embeddings was passed
        call_kwargs = mock_model.encode.call_args[1]
        self.assertTrue(call_kwargs["normalize_embeddings"])

    def test_embed_unsupported_provider(self):
        """Test unsupported provider raises error"""
        unsupported_model = EmbeddingModel.objects.create(
            name="custom-model",
            version="1",
            provider="unsupported-provider",
            dimensions=512,
        )

        with self.assertRaises(EmbeddingProviderError) as ctx:
            embed_texts(["Test"], embedding_model=unsupported_model)

        self.assertIn("Unsupported embedding provider", str(ctx.exception))

    def test_embed_empty_list(self):
        """Test embedding empty list returns empty list"""
        vectors = embed_texts([], embedding_model=self.openai_model)
        self.assertEqual(vectors, [])

    @override_settings(OPENAI_API_KEY="test-api-key")
    @patch("openai.OpenAI")
    def test_embed_openai_api_error(self, mock_openai_class):
        """Test OpenAI API error handling"""
        # Mock OpenAI client to raise exception
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.embeddings.create.side_effect = Exception("API error")

        # Test embedding - should raise EmbeddingProviderError
        with self.assertRaises(EmbeddingProviderError) as ctx:
            embed_texts(["Test"], embedding_model=self.openai_model)

        self.assertIn("OpenAI API error", str(ctx.exception))

    def test_get_embedding_dimensions_openai(self):
        """Test getting dimensions for OpenAI models"""
        # Known models
        self.assertEqual(
            get_embedding_dimensions("text-embedding-3-small", "openai"), 1536
        )
        self.assertEqual(
            get_embedding_dimensions("text-embedding-3-large", "openai"), 3072
        )
        self.assertEqual(
            get_embedding_dimensions("text-embedding-ada-002", "openai"), 1536
        )

        # Unknown model should raise error
        with self.assertRaises(EmbeddingProviderError):
            get_embedding_dimensions("unknown-model", "openai")

    @patch("sentence_transformers.SentenceTransformer")
    def test_get_embedding_dimensions_sentence_transformers(self, mock_st_class):
        """Test getting dimensions for sentence-transformers models"""
        # Mock model
        mock_model = Mock()
        mock_model.get_sentence_embedding_dimension.return_value = 768
        mock_st_class.return_value = mock_model

        dimensions = get_embedding_dimensions(
            "all-mpnet-base-v2", "sentence-transformers"
        )

        self.assertEqual(dimensions, 768)
        mock_st_class.assert_called_once_with("all-mpnet-base-v2")

    def test_get_embedding_dimensions_unknown_provider(self):
        """Test getting dimensions for unknown provider raises error"""
        with self.assertRaises(EmbeddingProviderError):
            get_embedding_dimensions("model-name", "unknown-provider")

    def test_embed_local_not_implemented(self):
        """Test local provider raises not implemented error"""
        local_model = EmbeddingModel.objects.create(
            name="custom-local",
            version="1",
            provider="local",
            dimensions=512,
        )

        with self.assertRaises(EmbeddingProviderError) as ctx:
            embed_texts(["Test"], embedding_model=local_model)

        self.assertIn("not yet implemented", str(ctx.exception))

    @override_settings(OPENAI_API_KEY="test-api-key")
    @patch("openai.OpenAI")
    def test_embed_multiple_batches(self, mock_openai_class):
        """Test embedding multiple texts"""
        # Mock OpenAI client
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Mock response with 5 embeddings
        mock_response = Mock()
        mock_response.data = [
            Mock(embedding=[0.1] * 1536),
            Mock(embedding=[0.2] * 1536),
            Mock(embedding=[0.3] * 1536),
            Mock(embedding=[0.4] * 1536),
            Mock(embedding=[0.5] * 1536),
        ]
        mock_client.embeddings.create.return_value = mock_response

        # Test embedding
        texts = [f"Text {i}" for i in range(5)]
        vectors = embed_texts(texts, embedding_model=self.openai_model)

        # Verify
        self.assertEqual(len(vectors), 5)
        for vector in vectors:
            self.assertEqual(len(vector), 1536)

    @patch.dict("os.environ", {}, clear=True)
    @patch("openai.OpenAI")
    def test_embed_openai_missing_api_key(self, mock_openai_class):
        """Test OpenAI embedding without API key raises error"""
        # Temporarily remove OPENAI_API_KEY from settings
        original_key = getattr(settings, "OPENAI_API_KEY", None)
        if hasattr(settings, "OPENAI_API_KEY"):
            delattr(settings, "OPENAI_API_KEY")

        try:
            with self.assertRaises(EmbeddingProviderError) as ctx:
                embed_texts(["Test"], embedding_model=self.openai_model)

            self.assertIn("OPENAI_API_KEY not configured", str(ctx.exception))
        finally:
            # Restore original setting
            if original_key is not None:
                settings.OPENAI_API_KEY = original_key
