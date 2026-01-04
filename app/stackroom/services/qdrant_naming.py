"""
Qdrant Collection Naming Strategy

Produces deterministic, collision-free collection names for vector storage.

Contract Rules:
- Collection names MUST be deterministic (same inputs → same output)
- NO randomness, timestamps, or environment-specific prefixes
- Collection scoped by (library, embedding_model)
- Names MUST be valid Qdrant collection identifiers
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID
    from stackroom.models import Library, EmbeddingModel


def get_collection_name(
    library_id: UUID | str,
    model_name: str,
    model_version: str,
) -> str:
    """
    Generate a deterministic Qdrant collection name.

    Format: stackroom__lib_<library_uuid>__emb__<model>__<version>

    Args:
        library_id: Library UUID (str or UUID object)
        model_name: Embedding model name (e.g., "text-embedding-3-small")
        model_version: Embedding model version (e.g., "1", "2024-01")

    Returns:
        Deterministic collection name string

    Examples:
        >>> get_collection_name(
        ...     "550e8400-e29b-41d4-a716-446655440000",
        ...     "text-embedding-3-small",
        ...     "1"
        ... )
        'stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__text-embedding-3-small__1'

        >>> get_collection_name(
        ...     "550e8400-e29b-41d4-a716-446655440000",
        ...     "bge-large-en-v1.5",
        ...     "2024-01"
        ... )
        'stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__bge-large-en-v1.5__2024-01'
    """
    # Convert UUID to string if needed
    lib_uuid_str = str(library_id)

    # Sanitize model name and version for safe collection naming
    # Qdrant collection names: alphanumeric, hyphen, underscore
    safe_model = _sanitize_component(model_name)
    safe_version = _sanitize_component(model_version)

    return f"stackroom__lib_{lib_uuid_str}__emb__{safe_model}__{safe_version}"


def get_collection_name_from_models(
    library: Library,
    embedding_model: EmbeddingModel,
) -> str:
    """
    Generate collection name from Django model instances.

    Args:
        library: Library model instance
        embedding_model: EmbeddingModel instance

    Returns:
        Deterministic collection name string
    """
    return get_collection_name(
        library_id=library.id,
        model_name=embedding_model.name,
        model_version=embedding_model.version,
    )


def _sanitize_component(component: str) -> str:
    """
    Sanitize a component for Qdrant collection name.

    Qdrant collection names support:
    - Letters (a-z, A-Z)
    - Numbers (0-9)
    - Hyphens (-)
    - Underscores (_)

    This function replaces any other characters with underscores.

    Args:
        component: String to sanitize

    Returns:
        Sanitized string safe for Qdrant collection names
    """
    # Replace any character that's not alphanumeric, hyphen, or underscore
    sanitized = re.sub(r"[^a-zA-Z0-9\-_]", "_", component)

    # Collapse multiple underscores to single underscore
    sanitized = re.sub(r"_+", "_", sanitized)

    # Remove leading/trailing underscores
    sanitized = sanitized.strip("_")

    return sanitized


def parse_collection_name(collection_name: str) -> dict[str, str] | None:
    """
    Parse a Stackroom collection name back into components.

    Useful for debugging, validation, and reconciliation tasks.

    Args:
        collection_name: Collection name string

    Returns:
        Dict with 'library_id', 'model_name', 'model_version' or None if invalid

    Examples:
        >>> parse_collection_name(
        ...     'stackroom__lib_550e8400-e29b-41d4-a716-446655440000__emb__text-embedding-3-small__1'
        ... )
        {
            'library_id': '550e8400-e29b-41d4-a716-446655440000',
            'model_name': 'text-embedding-3-small',
            'model_version': '1'
        }
    """
    pattern = r"^stackroom__lib_(?P<library_id>[a-f0-9\-]+)__emb__(?P<model_name>[a-zA-Z0-9\-_]+)__(?P<model_version>[a-zA-Z0-9\-_]+)$"

    match = re.match(pattern, collection_name)
    if not match:
        return None

    return match.groupdict()


def validate_collection_name(collection_name: str) -> bool:
    """
    Check if a collection name is a valid Stackroom collection.

    Args:
        collection_name: Collection name to validate

    Returns:
        True if valid Stackroom collection name, False otherwise
    """
    return parse_collection_name(collection_name) is not None
