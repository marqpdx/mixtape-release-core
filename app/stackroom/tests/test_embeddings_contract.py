"""
Embedding Contract Tests (Phase 2.1)

These tests enforce the embedding contract rules:
1. Retry does not create duplicates
2. Embedding never mutates IR
3. Library isolation is enforced
4. Stale embeddings are detectable

These tests MUST pass before any embedding pipeline work proceeds.
"""

import hashlib
from django.test import TestCase
from django.db import IntegrityError, transaction
from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    EmbeddingModel,
    ChunkEmbedding,
    EmbeddingStatus,
)


class EmbeddingContractTests(TestCase):
    """
    Authority Boundary Tests

    Contract Rule:
    - Django IR models are the sole source of truth for text, provenance, library isolation
    - Embeddings are derived data, never authoritative
    - Vector stores (Qdrant) are indexes, not databases
    """

    def setUp(self):
        """Create test fixtures"""
        # Create library
        self.library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant-123",
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
            hash_sha256="abc123" * 10,  # 64 char hash
        )

        # Create artifact
        self.artifact = Artifact.objects.create(
            source_file=self.source_file,
            artifact_uid="artifact-1",
            artifact_type="extracted_text",
            format="text/plain",
            text="This is test content for embeddings.",
        )

        # Create chunk
        self.chunk = Chunk.objects.create(
            artifact=self.artifact,
            chunk_strategy="test",
            text="This is test content for embeddings.",
            token_estimate=8,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 38}],
            hash_sha256=hashlib.sha256("This is test content for embeddings.".encode()).hexdigest(),
        )

        # Create embedding model
        self.embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

    def test_retry_does_not_create_duplicates(self):
        """
        CONTRACT: Idempotency Key

        The tuple (chunk, embedding_model, embedded_text_hash) is unique.
        Retrying an embedding operation MUST NOT create duplicate rows.
        """
        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()

        # Create first embedding
        embedding1 = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Attempt to create duplicate - should raise IntegrityError
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ChunkEmbedding.objects.create(
                    chunk=self.chunk,
                    embedding_model=self.embedding_model,
                    library=self.library,
                    embedded_text_hash=text_hash,
                    qdrant_collection="test-collection",
                    qdrant_point_id=str(self.chunk.id),
                    status=EmbeddingStatus.PENDING,
                )

        # Verify only one embedding exists
        count = ChunkEmbedding.objects.filter(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
        ).count()
        self.assertEqual(count, 1)

    def test_embedding_never_mutates_ir(self):
        """
        CONTRACT: Authority Boundary

        Creating, updating, or deleting embeddings MUST NEVER modify:
        - Chunk.text
        - Chunk.source_spans
        - Artifact, SourceFile, or Library relationships
        """
        original_text = self.chunk.text
        original_spans = self.chunk.source_spans.copy()
        original_artifact_id = self.chunk.artifact_id

        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()

        # Create embedding
        embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
        )

        # Refresh chunk from database
        self.chunk.refresh_from_db()

        # Verify IR is unchanged
        self.assertEqual(self.chunk.text, original_text)
        self.assertEqual(self.chunk.source_spans, original_spans)
        self.assertEqual(self.chunk.artifact_id, original_artifact_id)

        # Update embedding status
        embedding.mark_complete()
        embedding.save()

        # Refresh chunk again
        self.chunk.refresh_from_db()

        # Verify IR is still unchanged
        self.assertEqual(self.chunk.text, original_text)
        self.assertEqual(self.chunk.source_spans, original_spans)

        # Delete embedding
        embedding.delete()

        # Refresh chunk one more time
        self.chunk.refresh_from_db()

        # Verify IR is STILL unchanged
        self.assertEqual(self.chunk.text, original_text)
        self.assertEqual(self.chunk.source_spans, original_spans)

    def test_library_isolation_enforced(self):
        """
        CONTRACT: Library Isolation

        Embeddings MUST be scoped to libraries.
        Querying embeddings MUST enforce library boundaries.
        """
        # Create second library
        library2 = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant-456",
            name="Other Library",
        )

        # Create source file in library2
        source_file2 = SourceFile.objects.create(
            library=library2,
            origin="upload",
            path="other/other.txt",
            filename="other.txt",
            content_type="text/plain",
            size_bytes=100,
            hash_sha256="def456" * 10,  # 64 char hash
        )

        # Create artifact in library2
        artifact2 = Artifact.objects.create(
            source_file=source_file2,
            artifact_uid="artifact-2",
            artifact_type="extracted_text",
            format="text/plain",
            text="Content in other library.",
        )

        # Create chunk in library2
        chunk2 = Chunk.objects.create(
            artifact=artifact2,
            chunk_strategy="test",
            text="Content in other library.",
            token_estimate=5,
            order_index=0,
            source_spans=[{"char_start": 0, "char_end": 26}],
            hash_sha256=hashlib.sha256("Content in other library.".encode()).hexdigest(),
        )

        text_hash1 = hashlib.sha256(self.chunk.text.encode()).hexdigest()
        text_hash2 = hashlib.sha256(chunk2.text.encode()).hexdigest()

        # Create embeddings in both libraries
        embedding1 = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=text_hash1,
            qdrant_collection="lib1-collection",
            qdrant_point_id=str(self.chunk.id),
        )

        embedding2 = ChunkEmbedding.objects.create(
            chunk=chunk2,
            embedding_model=self.embedding_model,
            library=library2,
            embedded_text_hash=text_hash2,
            qdrant_collection="lib2-collection",
            qdrant_point_id=str(chunk2.id),
        )

        # Query library1 embeddings
        lib1_embeddings = ChunkEmbedding.objects.filter(library=self.library)
        self.assertEqual(lib1_embeddings.count(), 1)
        self.assertEqual(lib1_embeddings.first().chunk_id, self.chunk.id)

        # Query library2 embeddings
        lib2_embeddings = ChunkEmbedding.objects.filter(library=library2)
        self.assertEqual(lib2_embeddings.count(), 1)
        self.assertEqual(lib2_embeddings.first().chunk_id, chunk2.id)

        # Verify no cross-contamination
        self.assertNotEqual(lib1_embeddings.first().id, lib2_embeddings.first().id)

    def test_stale_embeddings_detectable(self):
        """
        CONTRACT: Drift Detection

        If chunk.text changes, the embedded_text_hash will no longer match.
        This MUST be detectable so stale embeddings can be identified.
        """
        original_text = "Original content."
        self.chunk.text = original_text
        self.chunk.save()

        original_hash = hashlib.sha256(original_text.encode()).hexdigest()

        # Create embedding with original text
        embedding = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=original_hash,
            qdrant_collection="test-collection",
            qdrant_point_id=str(self.chunk.id),
            status=EmbeddingStatus.COMPLETE,
        )

        # Simulate chunk text change (e.g., from IR correction)
        new_text = "Modified content."
        self.chunk.text = new_text
        self.chunk.save()

        new_hash = hashlib.sha256(new_text.encode()).hexdigest()

        # Verify hashes differ
        self.assertNotEqual(original_hash, new_hash)

        # Refresh embedding
        embedding.refresh_from_db()

        # Current chunk hash
        current_chunk_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()

        # Embedding hash should NOT match current chunk hash
        self.assertNotEqual(embedding.embedded_text_hash, current_chunk_hash)

        # This is how we detect stale embeddings
        is_stale = (embedding.embedded_text_hash != current_chunk_hash)
        self.assertTrue(is_stale, "Stale embedding should be detectable")

    def test_embedding_identity_completeness(self):
        """
        CONTRACT: Embedding Identity

        An embedding is uniquely identified by:
        (chunk, embedding_model, embedded_text_hash)

        If ANY of these change, a new embedding row is required.
        """
        text_hash = hashlib.sha256(self.chunk.text.encode()).hexdigest()

        # Create initial embedding
        embedding1 = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=self.embedding_model,
            library=self.library,
            embedded_text_hash=text_hash,
            qdrant_collection="collection-v1",
            qdrant_point_id=str(self.chunk.id),
        )

        # Create second embedding model (different version)
        embedding_model_v2 = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="2",  # Different version
            provider="openai",
            dimensions=1536,
        )

        # Should be able to create new embedding with different model
        embedding2 = ChunkEmbedding.objects.create(
            chunk=self.chunk,
            embedding_model=embedding_model_v2,  # Different model
            library=self.library,
            embedded_text_hash=text_hash,  # Same text hash
            qdrant_collection="collection-v2",
            qdrant_point_id=str(self.chunk.id),
        )

        # Both should exist
        count = ChunkEmbedding.objects.filter(chunk=self.chunk).count()
        self.assertEqual(count, 2)

        # Should have different IDs
        self.assertNotEqual(embedding1.id, embedding2.id)


class EmbeddingModelRegistryTests(TestCase):
    """
    Tests for EmbeddingModel registry behavior.

    Contract Rule:
    - EmbeddingModel rows are append-only in practice
    - (name, version) must be unique
    """

    def test_embedding_model_uniqueness(self):
        """
        CONTRACT: Registry Identity

        EmbeddingModel (name, version) pairs must be unique.
        """
        # Create first model
        model1 = EmbeddingModel.objects.create(
            name="test-model",
            version="1.0",
            provider="openai",
            dimensions=768,
        )

        # Attempt to create duplicate
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                EmbeddingModel.objects.create(
                    name="test-model",
                    version="1.0",  # Same name+version
                    provider="huggingface",  # Different provider
                    dimensions=1024,  # Different dimensions
                )

    def test_embedding_model_string_representation(self):
        """Verify model string representation is clear"""
        model = EmbeddingModel.objects.create(
            name="text-embedding-3-large",
            version="2024-01",
            provider="openai",
            dimensions=3072,
        )

        expected = "text-embedding-3-large@2024-01"
        self.assertEqual(str(model), expected)
