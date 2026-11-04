"""
Ariadne — P8: embeddings and hybrid search (build spec §14 Phase B, §19.1).

Embedding model decided 2026-11-04 (CTO, build spec §17 OQ3): reuse
Stackroom's own choice rather than introduce a second one -- `fastembed`,
`BAAI/bge-small-en-v1.5`, 384 dimensions, cosine distance. Deterministic,
local, CPU-only (matches core's force_cpu setup); Qdrant similarity search
itself does not invoke the model (build spec §11).

Qdrant point id = Passage.id (str). Payload carries just enough to filter
without a DB round trip: document_id, revision_id, candidate text is
fetched from Postgres afterward, not stored twice in Qdrant.
"""

from __future__ import annotations

from functools import lru_cache

from django.conf import settings

EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384


@lru_cache(maxsize=1)
def _get_model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBEDDING_MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """CPU-bound; call from a management command or a sync view, not the
    event loop (this codebase is sync Django, so that's not a concern
    here the way it is in Stackroom's async process)."""
    if not texts:
        return []
    model = _get_model()
    return [vector.tolist() for vector in model.embed(texts)]


@lru_cache(maxsize=1)
def get_qdrant_client():
    from qdrant_client import QdrantClient

    return QdrantClient(url=settings.QDRANT_URL)


def ensure_collection() -> None:
    """Idempotent. Qdrant vector size is collection-bound (same note as
    Stackroom's own qdrant/client.py) -- this is why the model/dimension
    decision (§17 OQ3) had to land before this could be written at all."""
    from qdrant_client.http.models import Distance, VectorParams

    client = get_qdrant_client()
    existing = {c.name for c in client.get_collections().collections}
    if settings.ARIADNE_QDRANT_COLLECTION in existing:
        return
    client.create_collection(
        collection_name=settings.ARIADNE_QDRANT_COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
    )


def get_vectors(passage_ids: list[str]) -> dict[str, list[float]]:
    """Fetch already-stored embeddings by Passage id, for P9's Map step
    (deterministic clustering, build spec §19.2 step 3). Ids missing from
    Qdrant (not yet embedded) are simply absent from the result -- callers
    fall back to embedding their text on the fly."""
    if not passage_ids:
        return {}
    ensure_collection()
    points = get_qdrant_client().retrieve(
        collection_name=settings.ARIADNE_QDRANT_COLLECTION, ids=passage_ids, with_vectors=True,
    )
    return {str(point.id): point.vector for point in points}


def embed_pending_passages(batch_size: int = 64) -> int:
    """Embeds every Passage not yet embedded. Returns the count embedded.
    Safe to re-run: already-embedded passages are skipped via
    embedding_status, matching ariadne_ingest_snapshot's own idempotency
    pattern (P5's first real Discovery Run)."""
    from qdrant_client.http.models import PointStruct

    from .models import Passage

    ensure_collection()
    client = get_qdrant_client()

    pending = list(Passage.objects.filter(embedding_status="none").select_related("revision__document"))
    embedded_count = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embed_texts([p.text for p in batch])
        points = [
            PointStruct(
                id=str(passage.id),
                vector=vector,
                payload={
                    "document_id": str(passage.revision.document_id),
                    "revision_id": str(passage.revision_id),
                },
            )
            for passage, vector in zip(batch, vectors)
        ]
        client.upsert(collection_name=settings.ARIADNE_QDRANT_COLLECTION, points=points)
        Passage.objects.filter(id__in=[p.id for p in batch]).update(embedding_status="embedded")
        embedded_count += len(batch)

    return embedded_count
