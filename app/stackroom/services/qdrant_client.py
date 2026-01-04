"""
Qdrant Client Wrapper

Isolates Qdrant SDK and makes the system storage-agnostic.

Contract Rules:
- Qdrant is treated as an INDEX, not a database
- Payloads contain IDs only (no text, no provenance)
- Collections are deterministic (same inputs → same collection)
- Writes are idempotent
- Reads must be validated against Django models
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

if TYPE_CHECKING:
    from stackroom.models import ChunkEmbedding

logger = logging.getLogger(__name__)


class QdrantClientWrapper:
    """
    Wrapper around Qdrant SDK for vector storage.

    Provides idempotent, contract-compliant operations.
    """

    def __init__(self, url: str | None = None, api_key: str | None = None):
        """
        Initialize Qdrant client.

        Args:
            url: Qdrant server URL (defaults to settings.QDRANT_URL)
            api_key: Qdrant API key (defaults to settings.QDRANT_API_KEY)
        """
        self.url = url or getattr(settings, "QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key or getattr(settings, "QDRANT_API_KEY", None)

        # Initialize Qdrant client
        self.client = QdrantClient(
            url=self.url,
            api_key=self.api_key,
            timeout=30,
        )

    def ensure_collection(
        self,
        collection_name: str,
        dimensions: int,
        distance: str = "Cosine",
    ) -> bool:
        """
        Ensure a collection exists with the correct configuration.

        Idempotent: safe to call multiple times.

        Args:
            collection_name: Name of collection
            dimensions: Vector dimensions
            distance: Distance metric ("Cosine", "Euclid", "Dot")

        Returns:
            True if collection was created, False if already existed

        Raises:
            Exception: If collection exists with mismatched dimensions
        """
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            existing = next(
                (c for c in collections if c.name == collection_name),
                None,
            )

            if existing:
                # Verify dimensions match
                # Note: Qdrant API returns config with vector params
                collection_info = self.client.get_collection(collection_name)
                config_dim = collection_info.config.params.vectors.size

                if config_dim != dimensions:
                    raise ValueError(
                        f"Collection {collection_name} exists with {config_dim} dimensions, "
                        f"expected {dimensions}"
                    )

                logger.info(f"Collection {collection_name} already exists")
                return False

            # Create collection
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=qdrant_models.VectorParams(
                    size=dimensions,
                    distance=qdrant_models.Distance[distance.upper()],
                ),
            )

            logger.info(
                f"Created collection {collection_name} with {dimensions} dimensions"
            )
            return True

        except UnexpectedResponse as e:
            # Handle 409 Conflict - collection was created by another task (race condition)
            if "already exists" in str(e).lower():
                logger.info(
                    f"Collection {collection_name} was created by another task "
                    "(race condition resolved)"
                )
                # Verify dimensions match
                try:
                    collection_info = self.client.get_collection(collection_name)
                    config_dim = collection_info.config.params.vectors.size
                    if config_dim != dimensions:
                        raise ValueError(
                            f"Collection {collection_name} created with {config_dim} dimensions, "
                            f"expected {dimensions}"
                        )
                    return False  # Collection exists (created by another task)
                except Exception as verify_error:
                    logger.error(f"Failed to verify collection after conflict: {verify_error}")
                    raise
            else:
                logger.error(f"Qdrant error ensuring collection: {e}")
                raise

    def upsert_point(
        self,
        collection_name: str,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """
        Upsert a vector point into a collection.

        Idempotent: upserting the same point_id replaces the existing point.

        Contract Rule: Payload MUST contain IDs only.
        Expected keys: chunk_id, library_id, embedding_model_id

        Args:
            collection_name: Name of collection
            point_id: Point ID (string/uuid)
            vector: Embedding vector
            payload: Metadata (IDs only)

        Raises:
            Exception: If upsert fails
        """
        # Validate payload contains only IDs
        self._validate_payload(payload)

        try:
            point = qdrant_models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )

            self.client.upsert(
                collection_name=collection_name,
                points=[point],
                wait=True,  # Wait for indexing to complete
            )

            logger.debug(f"Upserted point {point_id} to {collection_name}")

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error upserting point: {e}")
            raise

    def search(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar vectors in a collection.

        Args:
            collection_name: Name of collection to search
            vector: Query vector
            limit: Maximum number of results
            score_threshold: Minimum similarity score (optional)

        Returns:
            List of dicts with keys: point_id, score, chunk_id, library_id, embedding_model_id

        Raises:
            Exception: If search fails
        """
        try:
            results = self.client.query_points(
                collection_name=collection_name,
                query=vector,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            ).points

            # Convert to clean dict format
            output = []
            for hit in results:
                output.append(
                    {
                        "point_id": str(hit.id),
                        "score": hit.score,
                        **hit.payload,  # chunk_id, library_id, embedding_model_id
                    }
                )

            return output

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error searching collection: {e}")
            raise

    def delete_point(
        self,
        collection_name: str,
        point_id: str,
    ) -> None:
        """
        Delete a point from a collection.

        Idempotent: deleting a non-existent point is a no-op.

        Args:
            collection_name: Name of collection
            point_id: Point ID to delete
        """
        try:
            self.client.delete(
                collection_name=collection_name,
                points_selector=qdrant_models.PointIdsList(
                    points=[point_id],
                ),
                wait=True,
            )

            logger.debug(f"Deleted point {point_id} from {collection_name}")

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error deleting point: {e}")
            raise

    def delete_collection(self, collection_name: str) -> None:
        """
        Delete an entire collection.

        Use with caution: this destroys all vectors in the collection.

        Args:
            collection_name: Name of collection to delete
        """
        try:
            self.client.delete_collection(collection_name=collection_name)
            logger.info(f"Deleted collection {collection_name}")

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error deleting collection: {e}")
            raise

    def collection_exists(self, collection_name: str) -> bool:
        """
        Check if a collection exists.

        Args:
            collection_name: Name of collection

        Returns:
            True if collection exists, False otherwise
        """
        try:
            collections = self.client.get_collections().collections
            return any(c.name == collection_name for c in collections)

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error checking collection: {e}")
            raise

    def get_point(
        self,
        collection_name: str,
        point_id: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve a point by ID.

        Args:
            collection_name: Name of collection
            point_id: Point ID to retrieve

        Returns:
            Dict with point data or None if not found
        """
        try:
            points = self.client.retrieve(
                collection_name=collection_name,
                ids=[point_id],
                with_payload=True,
                with_vectors=True,
            )

            if not points:
                return None

            point = points[0]
            return {
                "point_id": str(point.id),
                "vector": point.vector,
                "payload": point.payload,
            }

        except UnexpectedResponse as e:
            logger.error(f"Qdrant error retrieving point: {e}")
            raise

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> None:
        """
        Validate that payload contains only IDs.

        Contract Rule: No text, no provenance, no human-readable content.

        Args:
            payload: Payload dict to validate

        Raises:
            ValueError: If payload contains forbidden keys
        """
        required_keys = {"chunk_id", "library_id", "embedding_model_id"}
        forbidden_keys = {"text", "content", "spans", "provenance", "source"}

        # Check for required keys
        missing_keys = required_keys - set(payload.keys())
        if missing_keys:
            raise ValueError(f"Payload missing required keys: {missing_keys}")

        # Check for forbidden keys
        found_forbidden = set(payload.keys()) & forbidden_keys
        if found_forbidden:
            raise ValueError(
                f"Payload contains forbidden keys: {found_forbidden}. "
                "Only IDs allowed per embedding contract."
            )

        # Validate ID types (should be strings or UUIDs)
        for key, value in payload.items():
            if key in required_keys:
                if not isinstance(value, (str, UUID, int)):
                    raise ValueError(
                        f"Payload key {key} must be str/UUID/int, got {type(value)}"
                    )


def build_payload_from_embedding(chunk_embedding: ChunkEmbedding) -> dict[str, str]:
    """
    Build a Qdrant payload from a ChunkEmbedding instance.

    Contract: IDs + embedded_text_hash for freshness detection, no full text or provenance.
    Also includes chunk_type for search ranking/filtering.

    Args:
        chunk_embedding: ChunkEmbedding model instance

    Returns:
        Dict with chunk_id, library_id, embedding_model_id, embedded_text_hash, chunk_type
    """
    # Get chunk_type from chunk's source_spans metadata
    chunk = chunk_embedding.chunk
    chunk_type = 'body'  # default
    if chunk.source_spans and isinstance(chunk.source_spans, list) and len(chunk.source_spans) > 0:
        first_span = chunk.source_spans[0]
        if isinstance(first_span, dict) and 'chunk_type' in first_span:
            chunk_type = first_span['chunk_type']

    return {
        "chunk_id": str(chunk_embedding.chunk_id),
        "library_id": str(chunk_embedding.library_id),
        "embedding_model_id": str(chunk_embedding.embedding_model_id),
        "embedded_text_hash": chunk_embedding.embedded_text_hash,
        "chunk_type": chunk_type,
    }


# Global client instance (lazy-initialized)
_client: QdrantClientWrapper | None = None


def get_qdrant_client() -> QdrantClientWrapper:
    """
    Get the global Qdrant client instance.

    Lazy-initializes on first call.

    Returns:
        QdrantClientWrapper instance
    """
    global _client
    if _client is None:
        _client = QdrantClientWrapper()
    return _client
