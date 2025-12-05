# ai/scripts/ingest_approved_ingestion.py

import logging


logger = logging.getLogger(__name__)

import requests
from llama_index.core.schema import Document

from inkwell.config.custom_settings import Settings
from inkwell.models import IngestedAsset
from inkwell.scripts.ingest_helpers import (
    MetadataPrefixedSemanticSplitter,
    add_default_metadata,
    clean_text,
    extract_gutenberg_metadata,
    extract_main_text,
)


def ingest_approved_asset(asset, index):
    if not hasattr(asset, "gutenberg_info") or not asset.gutenberg_info.text_url:
        logger.warning(" Skipping ingestion: no text_url for asset {asset.id} - '%s'", asset.title)
        return None

    text_url = asset.gutenberg_info.text_url

    try:
        response = requests.get(text_url, timeout=30)
        response.raise_for_status()
        text = response.text
        asset.retrieved = True
        asset.save()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.error(" Text file not found (404) for asset {asset.id} — %s", text_url)
        else:
            logger.error(" HTTP error for asset {asset.id}: %s", e)
        asset.notes = f"Download failed: {e}"
        asset.save()
        return None
    except Exception as e:
        logger.error(" Unexpected error for asset {asset.id}: %s", e)
        asset.notes = f"Unexpected error: {e}"
        asset.save()
        return None

    gutenberg_metadata = extract_gutenberg_metadata(text)

    metadata = {
        "title": asset.title or gutenberg_metadata.get("title", "Unknown Title"),
        "author": asset.author or gutenberg_metadata.get("author", "Unknown Author"),
        "release_date": gutenberg_metadata.get("release_date", "Unknown"),
    }

    logger.info("📥 Starting ingestion for approved asset: {asset.title}")
    cleaned = clean_text(extract_main_text(text))

    doc = Document(text=cleaned, metadata={"filename": text_url, **metadata})
    splitter = MetadataPrefixedSemanticSplitter(
        llm=Settings.llm,
        embed_model=Settings.embed_model,
        buffer_size=1,
        breakpoint_percentile_threshold=95,
    )
    nodes = splitter.get_nodes_from_documents([doc])
    if not nodes:
        logger.info("⚠️ No chunks generated")
        return { "success": False, "error": "No chunks generated" }

    add_default_metadata(nodes, metadata, text_url)
    index.insert_nodes(nodes)
    index.storage_context.persist()

    # Calculate total tokens (approximate word count)
    total_tokens = sum(len(node.text.split()) for node in nodes)

    IngestedAsset.objects.create(
        suggested_asset=asset,
        node_count=len(nodes),
        token_count=total_tokens,
        embedding_model=str(Settings.embed_model),
        notes="Auto-ingested after approval.",
    )

    logger.info(" Ingested approved asset: %s", asset.title)
    return { "success": True, "nodes": nodes }
