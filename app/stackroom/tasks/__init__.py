# app/stackroom/tasks/__init__.py

from .embeddings import (
    embed_library,
    embed_chunk_embedding,
    embed_pending_batch,
)

from .retrieval import (
    log_query_async,
)

from .processing import (
    process_artifact,
)

__all__ = [
    "embed_library",
    "embed_chunk_embedding",
    "embed_pending_batch",
    "log_query_async",
    "process_artifact",
]
