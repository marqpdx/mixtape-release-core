# ai/config/ai_config.py

import logging


logger = logging.getLogger(__name__)

import os
import re
from collections import defaultdict
from pathlib import Path

from llama_index.core import Settings as LlamaIndexSettings
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever, VectorIndexRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from inkwell.config.custom_settings import Settings
from inkwell.config.llm_config import configure_llm
from inkwell.scripts.documents_pg import SimpleBM25Retriever


# ==== Constants ====
retriever: BaseRetriever | None = None  # global retriever instance (optional)
collection_name = "gutenberg25"


# ==== Helpers ====

def strip_embedded_qa(text: str) -> str:
    """Remove embedded Q&A patterns like 'Query: ... Answer: ...'."""
    return re.sub(r"(Query:.*?Answer:.*?)(?=(\nQuery:|\Z))", "", text, flags=re.DOTALL)


def configure_embedding():
    logger.info("📦 Configuring embedding...")
    try:
        Settings.embed_model = HuggingFaceEmbedding(
            model_name="BAAI/bge-base-en",
            device="cpu",  # or "cuda" if you ever go GPU
            embed_batch_size=8  # 🔽 reduce from default 32–64
        )


        LlamaIndexSettings.embed_model = Settings.embed_model
        logger.info("✅ Embedding model 'BAAI/bge-base-en' loaded.")
    except Exception as e:
        logger.error(" Failed to load embedding model: %s", e)


def build_retriever(
    index: VectorStoreIndex,
    collection_name: str,
    vector_weight: float = 0.7,
    bm25_weight: float = 0.3,
    default_priority: int = 0
    ) -> BaseRetriever :

    vector_retriever = VectorIndexRetriever(index=index, similarity_top_k=5)

    BM25_INDEX_DIR = Path(os.getenv("BM25_INDEX_DIR", "~/.cdoc_cache/bm25_indexes")).expanduser()

    # bm25_path = f"./ai/bm25/bm25_indexes/{collection_name}.json"
    bm25_path = f"{BM25_INDEX_DIR}/{collection_name}.json"
    bm25_retriever = None

    if os.path.exists(bm25_path):
        bm25_retriever = SimpleBM25Retriever.load_from_path(bm25_path, k=5)
        logger.info("✅ BM25 retriever loaded.")
    else:
        logger.warning(" BM25 file not found at %s — using vector retriever only.", bm25_path)

    class ManualEnsembleRetriever(BaseRetriever):
        def _retrieve(self, query: str) -> list[NodeWithScore]:
            vector_results = vector_retriever.retrieve(query)
            if not bm25_retriever:
                return vector_results

            bm25_results = bm25_retriever.retrieve(query)

            score_map = defaultdict(float)
            node_map = {}

            for result in bm25_results:
                node_id = result.node.node_id
                score_map[node_id] += bm25_weight * result.score
                node_map[node_id] = result.node

            for result in vector_results:
                node_id = result.node.node_id
                score_map[node_id] += vector_weight * result.score
                node_map[node_id] = result.node

            combined = [
                NodeWithScore(node=node_map[node_id], score=score)
                for node_id, score in score_map.items()
            ]
            return sorted(combined, key=lambda nws: nws.score, reverse=True)

    base_retriever = ManualEnsembleRetriever()

    class CleanedRetriever(BaseRetriever):
        def _retrieve(self, query: str) -> list[NodeWithScore]:
            nodes_with_scores = base_retriever.retrieve(query)

            for nws in nodes_with_scores:
                nws.node.text = strip_embedded_qa(nws.node.text)

            for i, nws in enumerate(nodes_with_scores):
                logger.info("\n🧼 Cleaned Node {i}:\n{nws.node.text[:300]}\n")

            sorted_nodes = sorted(
                nodes_with_scores,
                key=lambda nws: nws.node.metadata.get("priority", default_priority),
                reverse=True
            )

            for i, nws in enumerate(sorted_nodes):
                logger.info("[Node {i}] priority={nws.node.metadata.get('priority')} title={nws.node.metadata.get('title')}\n")

            return sorted_nodes

    return CleanedRetriever()

def configure_rag(index: VectorStoreIndex, collection_name: str):
    global retriever

    logger.info("🔧 Configuring RAG...")

    if not getattr(LlamaIndexSettings, "embed_model", None):
        configure_embedding()

    if not getattr(LlamaIndexSettings, "llm", None):
        configure_llm()

    if retriever is None:

        retriever = build_retriever(
            index=index,
            collection_name=collection_name,
            vector_weight=0.65,
            bm25_weight=0.35,
            default_priority=5
        )
        logger.info("✅ Retriever built and ready.")

    logger.info("🟢 RAG setup complete.")




    # What this module does:

    # 🧠 Connects a local AI model (LLM) and a document search system for answering questions using your private content (e.g. ebooks).

    # 🧩 Blends two search techniques: traditional keyword search (BM25) and modern semantic search (vector embeddings) for better accuracy.

    # 🏷️ Ranks document chunks using a combination of relevance score and optional document priority metadata (e.g. give internal docs more weight).

    # 🧼 Cleans up noisy content (like old Q&A traces embedded in documents) before sending to the model.

    # ⚖️ Supports weight tuning so you can control how much to trust keyword matches vs semantic matches.

    # 🛠️ Prepares everything once at startup, so your question-answering system is fast and ready during use.

    # 💬 Outputs rich debug info during setup to aid transparency and traceability.
