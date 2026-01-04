"""
Tests for Qdrant Collection Naming Strategy

Verifies deterministic, collision-free collection naming.
"""

from django.test import TestCase
from uuid import UUID

from stackroom.services.qdrant_naming import (
    get_collection_name,
    get_collection_name_from_models,
    parse_collection_name,
    validate_collection_name,
    _sanitize_component,
)
from stackroom.models import Library, EmbeddingModel


class QdrantNamingTests(TestCase):
    """Test Qdrant collection naming utilities"""

    def test_deterministic_naming(self):
        """Same inputs always produce same collection name"""
        lib_id = "550e8400-e29b-41d4-a716-446655440000"
        model = "text-embedding-3-small"
        version = "1"

        name1 = get_collection_name(lib_id, model, version)
        name2 = get_collection_name(lib_id, model, version)

        self.assertEqual(name1, name2)
        self.assertEqual(
            name1,
            "stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__text-embedding-3-small__1",
        )

    def test_uuid_object_conversion(self):
        """Collection naming works with UUID objects"""
        lib_uuid = UUID("550e8400-e29b-41d4-a716-446655440000")
        lib_str = "550e8400-e29b-41d4-a716-446655440000"

        name_from_uuid = get_collection_name(lib_uuid, "test-model", "1")
        name_from_str = get_collection_name(lib_str, "test-model", "1")

        self.assertEqual(name_from_uuid, name_from_str)

    def test_different_libraries_different_collections(self):
        """Different libraries get different collection names"""
        lib1 = "550e8400-e29b-41d4-a716-446655440000"
        lib2 = "660e8400-e29b-41d4-a716-446655440000"

        name1 = get_collection_name(lib1, "model", "1")
        name2 = get_collection_name(lib2, "model", "1")

        self.assertNotEqual(name1, name2)

    def test_different_models_different_collections(self):
        """Different embedding models get different collection names"""
        lib = "550e8400-e29b-41d4-a716-446655440000"

        name1 = get_collection_name(lib, "text-embedding-3-small", "1")
        name2 = get_collection_name(lib, "text-embedding-3-large", "1")

        self.assertNotEqual(name1, name2)

    def test_different_versions_different_collections(self):
        """Different model versions get different collection names"""
        lib = "550e8400-e29b-41d4-a716-446655440000"

        name1 = get_collection_name(lib, "text-embedding-3-small", "1")
        name2 = get_collection_name(lib, "text-embedding-3-small", "2")

        self.assertNotEqual(name1, name2)

    def test_sanitize_component(self):
        """Unsafe characters are sanitized"""
        # Spaces become underscores
        self.assertEqual(_sanitize_component("model name"), "model_name")

        # Special chars become underscores
        self.assertEqual(_sanitize_component("model@2024"), "model_2024")

        # Multiple underscores collapsed
        self.assertEqual(_sanitize_component("model___name"), "model_name")

        # Leading/trailing underscores removed
        self.assertEqual(_sanitize_component("_model_"), "model")

        # Safe chars preserved
        self.assertEqual(_sanitize_component("text-embedding-3_small"), "text-embedding-3_small")

    def test_parse_collection_name(self):
        """Collection names can be parsed back to components"""
        name = "stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__text-embedding-3-small__1"

        parsed = parse_collection_name(name)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["library_id"], "550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(parsed["model_name"], "text-embedding-3-small")
        self.assertEqual(parsed["model_version"], "1")

    def test_parse_invalid_collection_name(self):
        """Invalid collection names return None"""
        # Random name
        self.assertIsNone(parse_collection_name("random_collection"))

        # Wrong prefix
        self.assertIsNone(parse_collection_name("other__lib_uuid__emb__model__1"))

        # Missing components
        self.assertIsNone(parse_collection_name("stackroom__lib_uuid__emb__model"))

    def test_validate_collection_name(self):
        """Validation correctly identifies valid/invalid names"""
        # Valid name
        valid = "stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__text-embedding-3-small__1"
        self.assertTrue(validate_collection_name(valid))

        # Invalid name
        invalid = "random_collection"
        self.assertFalse(validate_collection_name(invalid))

    def test_get_collection_name_from_models(self):
        """Collection naming works with Django model instances"""
        # Create library
        library = Library.objects.create(
            tenant_type="group",
            tenant_id="test-tenant",
            name="Test Library",
        )

        # Create embedding model
        embedding_model = EmbeddingModel.objects.create(
            name="text-embedding-3-small",
            version="1",
            provider="openai",
            dimensions=1536,
        )

        # Get collection name
        collection_name = get_collection_name_from_models(library, embedding_model)

        # Verify format
        self.assertTrue(collection_name.startswith("stackroom__lib_"))
        self.assertIn("__emb__text-embedding-3-small__1", collection_name)

        # Verify it's parseable
        parsed = parse_collection_name(collection_name)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["library_id"], str(library.id))
        self.assertEqual(parsed["model_name"], "text-embedding-3-small")
        self.assertEqual(parsed["model_version"], "1")

    def test_roundtrip_consistency(self):
        """Collection names can be generated and parsed consistently"""
        lib_id = "550e8400-e29b-41d4-a716-446655440000"
        # Use names that don't need sanitization for perfect roundtrip
        model_name = "text-embedding-3-small"
        model_version = "2024-01"

        # Generate name
        name = get_collection_name(lib_id, model_name, model_version)

        # Parse it back
        parsed = parse_collection_name(name)

        # Verify consistency
        self.assertEqual(parsed["library_id"], lib_id)
        self.assertEqual(parsed["model_name"], model_name)
        self.assertEqual(parsed["model_version"], model_version)

    def test_roundtrip_with_sanitization(self):
        """Collection names with sanitized components can still be parsed"""
        lib_id = "550e8400-e29b-41d4-a716-446655440000"
        # Model name with dot - will be sanitized
        model_name = "bge-large-en-v1.5"
        model_version = "2024-01"

        # Generate name (will sanitize the dot to underscore)
        name = get_collection_name(lib_id, model_name, model_version)

        # Parse it back
        parsed = parse_collection_name(name)

        # Verify the sanitized version is parseable
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["library_id"], lib_id)
        # The dot was sanitized to underscore
        self.assertEqual(parsed["model_name"], "bge-large-en-v1_5")
        self.assertEqual(parsed["model_version"], model_version)

    def test_no_randomness(self):
        """Collection names never contain random elements"""
        lib_id = "550e8400-e29b-41d4-a716-446655440000"

        # Generate name 100 times
        names = [get_collection_name(lib_id, "model", "1") for _ in range(100)]

        # All should be identical
        self.assertEqual(len(set(names)), 1)

    def test_special_model_names(self):
        """Handle model names with special formatting"""
        lib_id = "550e8400-e29b-41d4-a716-446655440000"

        # Model with dots
        name1 = get_collection_name(lib_id, "model.v1.5", "1")
        self.assertIn("model_v1_5", name1)

        # Model with slashes
        name2 = get_collection_name(lib_id, "org/model-name", "1")
        self.assertIn("org_model-name", name2)
