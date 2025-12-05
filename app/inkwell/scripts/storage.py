# storage.py

import time

from django.conf import settings
from llama_index.core import StorageContext, VectorStoreIndex

# from llama_index.core.storage import StorageContext
# from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse


def load_or_create_index(collection_name="gutenberg-embeddings"):
    # qdrant_client = QdrantClient("http://localhost:6333")
    qdrant_client = QdrantClient(settings.QDRANT_URL)

    vector_store = QdrantVectorStore(client=qdrant_client, collection_name=collection_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    # Attempt to use an existing collection
    try:
        qdrant_client.get_collection(collection_name=collection_name)
        logger.info("✔ Collection '{collection_name}' found. Loading existing index.")
        vic = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            storage_context=storage_context
        )
        return vic

    except UnexpectedResponse:
        logger.info("⚠ Collection '{collection_name}' not found. Creating new index.")
        index = VectorStoreIndex([], storage_context=storage_context)
        index.storage_context.persist()
        return index





