# inkwell/scripts/ingest_helpers.py

import logging


logger = logging.getLogger(__name__)

import hashlib
import re
import tempfile
import threading
from pathlib import Path
from typing import List

import requests
from django.conf import settings
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core.schema import Document, TextNode
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient


# from inkwell.scripts.documents_pg import ingest_documents


# from inkwell.models import SuggestedAsset  # or import as needed
# from inkwell.scripts import ingest_documents

# === Custom Splitter ===
class MetadataPrefixedSemanticSplitter(SemanticSplitterNodeParser):
    def get_nodes_from_documents(self, documents: list[Document], show_progress: bool = True) -> list[TextNode]:
        nodes = super().get_nodes_from_documents(documents, show_progress)
        for node in nodes:
            title = node.metadata.get("title", "Unknown Title")
            author = node.metadata.get("author", "Unknown Author")
            prefix = f"passage: [Title: {title}] [Author: {author}]\n\n"
            node.text = prefix + node.text
        return nodes


# === Helpers ===

def ingest_documents_from_url(url: str, title: str, collection_name="drocuments"):
    logger.info("📥 Downloading and ingesting: {title}")

    # Download to temp file
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as f:
        f.write(response.text)
        tmp_path = f.name

    # Load Qdrant and index
    qdrant_client = QdrantClient(settings.QDRANT_URL)
    vector_store = QdrantVectorStore(client=qdrant_client, collection_name=collection_name)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    # Ingest
    from inkwell.scripts.documents_pg import ingest_documents
    ingest_documents(index=index, doc_path=tmp_path, collection_name=collection_name)

    # Cleanup or keep file
    logger.info(" Ingestion complete for {title} from %s", url)
    return tmp_path  # optionally return file path


def start_ingest_in_background(suggested_book):
    def task():

        if not hasattr(suggested_book, "gutenberg_info") or not suggested_book.gutenberg_info.text_url:
            # logger.warning(" Skipping ingestion: no text_url for asset {asset.id} - '%s'", asset.title)
            return  # or `continue` if in a loop

        ingest_documents_from_url(suggested_book.gutenberg_info.text_url, suggested_book.title)
        suggested_book.ingested = True
        suggested_book.save()

    threading.Thread(target=task, daemon=True).start()


def extract_gutenberg_metadata(text: str) -> dict:
    return {
        "title": re.search(r"Title:\s*(.*)", text).group(1).strip() if re.search(r"Title:\s*(.*)", text) else "Unknown Title",
        "author": re.search(r"Author:\s*(.*)", text).group(1).strip() if re.search(r"Author:\s*(.*)", text) else "Unknown Author",
        "release_date": re.search(r"Release Date:\s*(.*)", text).group(1).strip() if re.search(r"Release Date:\s*(.*)", text) else "Unknown Date",
    }


def extract_main_text(text: str) -> str:
        start = text.find("*** START OF")
        end = text.find("*** END OF")
        return text[start:end] if start != -1 and end != -1 else text


def clean_text(text: str) -> str:
    text = re.sub(r"\[Illustration:.*?\]", "", text)
    text = re.sub(r"\[Footnote:.*?\]", "", text)
    text = re.sub(r"\[Page [^\]]+\]", "", text)
    text = re.sub(r"\[\s*.*?\s*\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_file_hash(filepath: Path) -> str:
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def add_default_metadata(nodes: list[TextNode], metadata: dict, filepath: str):
    for node in nodes:
        node.metadata.update({
            "ref_doc_id": filepath,
            "source_type": "gutenberg",
            **metadata
        })
