# ai/scripts/documents_pg.py

import logging


logger = logging.getLogger(__name__)

import json
import os
import re
import time
from pathlib import Path
from typing import List

from llama_index.core import Settings
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import Document, NodeWithScore, TextNode
from rank_bm25 import BM25Okapi

from inkwell.models import IngestedFile
from inkwell.scripts.ingest_helpers import (
    MetadataPrefixedSemanticSplitter,
    add_default_metadata,
    clean_text,
    extract_gutenberg_metadata,
    extract_main_text,
    get_file_hash,
)


# === BM25 Retriever ===
class SimpleBM25Retriever(BaseRetriever):
    def __init__(self, nodes: list[TextNode], k: int = 5):
        self.k = k
        self.nodes = nodes
        self.corpus = [re.findall(r"\w+", node.text.lower()) for node in nodes]
        self.bm25 = BM25Okapi(self.corpus)

    def _retrieve(self, query: str) -> list[NodeWithScore]:
        # If it's a QueryBundle, extract the query string
        # Support both raw strings and LlamaIndex QueryBundle objects
        query_str = query.query_str if hasattr(query, "query_str") else query
        query_tokens = re.findall(r"\w+", query_str.lower())

        scores = self.bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:self.k]
        return [NodeWithScore(node=self.nodes[i], score=scores[i]) for i in top_indices]

    @classmethod
    def load_from_path(cls, path: str, k: int = 5):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        nodes = [TextNode.from_dict(item) for item in raw]
        return cls(nodes, k=k)


def update_bm25_metadata_file(collection_name: str, metadata: dict, filename: str, summary_path: str, node_count: int):
    summary_path = Path(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("progress a")

    if summary_path.exists():
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    else:
        summary = {
            "total_nodes": 0,
            "documents": []
        }

    try:
    # Check if this document is already recorded
        existing_filenames = {doc["filename"] for doc in summary["documents"]}
        if filename not in existing_filenames:
            summary["documents"].append({
                "filename": filename,
                "title": metadata.get("title", "Unknown Title"),
                "author": metadata.get("author", "Unknown Author"),
                "release_date": metadata.get("release_date", "Unknown"),
            })

    except Exception as e:
            logger.error(" Error processing {existing_filenames}: %s", e)

    summary["total_nodes"] = node_count

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    logger.info(" Updated BM25 summary for '{collection_name}' — %s documents tracked", len(summary["documents"]))


def append_nodes_to_bm25_file(new_nodes: list[TextNode], path: str, collection_name: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not new_nodes:
        logger.warning(" No new nodes to append for collection '%s'", collection_name)
        return

    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing_data = json.load(f)
        existing_nodes = [TextNode.from_dict(d) for d in existing_data]
    else:
        existing_nodes = []

    # Merge and deduplicate by node_id
    node_map = {node.node_id: node for node in existing_nodes}
    for node in new_nodes:
        node_map[node.node_id] = node  # overwrite if re-ingested

    combined_nodes = list(node_map.values())

    with open(path, "w", encoding="utf-8") as f:
        json.dump([node.to_dict() for node in combined_nodes], f)

    logger.info("🔄 Added {len(new_nodes)} new nodes, total now {len(combined_nodes)} in BM25 index for collection '{collection_name}'")


# === Main Ingestion Entry Point ===
def ingest_documents(index, doc_path: str, collection_name: str):
    start = time.time()

    BM25_INDEX_DIR = Path(os.getenv("BM25_INDEX_DIR", "~/.cdoc_cache/bm25_indexes")).expanduser()
    BM25_INDEX_DIR.mkdir(parents=True, exist_ok=True)

    bm25_path = f"{BM25_INDEX_DIR}/{collection_name}.json"
    bm25_meta_path = f"{BM25_INDEX_DIR}/{collection_name}_meta.json"

    logger.info("Running doc prep...")

    splitter = MetadataPrefixedSemanticSplitter(
        llm=Settings.llm,
        embed_model=Settings.embed_model,
        buffer_size=1,
        breakpoint_percentile_threshold=95,
    )

    all_nodes = []
    txt_files = list(Path(doc_path).glob("*.txt"))
    total_files = len(txt_files)

    for i, filepath in enumerate(txt_files, 1):
        logger.info("📦 Book {i} of {total_files}")
        filehash = get_file_hash(filepath)

        existing = IngestedFile.objects.filter(filehash=filehash, collection_name=collection_name).first()
        if existing:
            logger.info("Skipping already ingested file: {filepath.name}")
            if existing.filepath != str(filepath):
                existing.filepath = str(filepath)
                existing.save()
            continue

        try:
            raw_text = filepath.read_text(encoding="utf-8")
            metadata = extract_gutenberg_metadata(raw_text)
            logger.info("    └ Metadata: {metadata}")
            cleaned_text = clean_text(extract_main_text(raw_text))

            doc = Document(text=cleaned_text, metadata={"filename": filepath.name, **metadata})
            logger.info("📖 Processing file: {filepath.name}...")
            nodes = splitter.get_nodes_from_documents([doc])
            logger.info("    → {len(nodes)} chunks generated")

            if not nodes:
                logger.warning(" No chunks generated from %s", filepath.name)
                continue

            add_default_metadata(nodes, metadata, str(filepath))
            index.insert_nodes(nodes)
            index.storage_context.persist()

            append_nodes_to_bm25_file(nodes, bm25_path, collection_name)

            update_bm25_metadata_file(
                collection_name,
                metadata,
                filepath.name,
                bm25_meta_path,
                node_count=len(nodes)
            )

            IngestedFile.objects.create(
                filehash=filehash,
                filepath=str(filepath),
                collection_name=collection_name,
                title=metadata.get("title"),
                author=metadata.get("author"),
                release_date=metadata.get("release_date"),
            )

            logger.info(" Ingested file: %s", filepath.name)
            all_nodes.extend(nodes)

        except Exception as e:
            logger.error(" Error processing {filepath.name}: %s", e)

    end = time.time()
    logger.info("Doc Prep completed in {end - start:.2f} seconds\n")
    logger.info("✅ Chunking and indexing complete.\n")

    return all_nodes



# Executive-Level Summary (Tech-Aware Audience)

#     "How our AI system ingests and understands documents"

#     📚 We process open-access ebooks (e.g., from Project Gutenberg) about biology, life, and evolution.

#     ✂️ Each book is split into meaningful sections using an AI-powered chunking method that respects sentence boundaries and content flow.

#     🧠 Each chunk is encoded using a machine learning model into "vectors" (numerical fingerprints of meaning).

#     📊 We store these in a fast search engine (Qdrant) and also prep them for keyword-style search using BM25 (like how search engines work).

#     🔎 When you ask a question, our system pulls the most relevant chunks using both semantic similarity and keyword relevance—then the local AI model answers in natural language.

#     🛡️ We deduplicate and track ingestion, so each file is only processed once and linked to its metadata (title, author, etc.).
