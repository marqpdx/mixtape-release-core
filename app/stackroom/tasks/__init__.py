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

from .metadata import (
    extract_artifact_metadata_task,
    backfill_artifact_metadata,
)

from .milldraft import (
    create_milldraft_from_artifact_task,
)

__all__ = [
    "embed_library",
    "embed_chunk_embedding",
    "embed_pending_batch",
    "log_query_async",
    "process_artifact",
    "extract_artifact_metadata_task",
    "backfill_artifact_metadata",
    "create_milldraft_from_artifact_task",
]
