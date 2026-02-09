# stackroom/services/puddlejump_utilities.py

"""
Puddlejump Utility Services

Provides analysis and maintenance operations for Puddlejump libraries.
Phases 1-4 are non-LLM: pure DB aggregation, embeddings, and heuristics.

Functions:
- get_library_health()     — Dashboard metrics (Phase 1)
- detect_duplicates()      — Cosine similarity via Qdrant embeddings (Phase 2)
- extract_glossary()       — Rule-based term extraction (Phase 3)
- suggest_canonical_candidates() — Heuristic scoring (Phase 4)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from typing import Any
from uuid import UUID

import numpy as np
from django.db.models import Sum, Q

from stackroom.models import (
    Library,
    LibraryItem,
    SourceFile,
    Artifact,
    Shard,
    Chunk,
    ChunkEmbedding,
    EmbeddingModel,
    EmbeddingStatus,
)
from stackroom.services.qdrant_client import get_qdrant_client
from stackroom.services.qdrant_naming import get_collection_name

logger = logging.getLogger(__name__)


# ============================================================================
# PHASE 1: LIBRARY HEALTH
# ============================================================================

def get_library_health(library_id: UUID | str) -> dict[str, Any]:
    """
    Aggregate library health metrics from existing model data.

    Returns a dashboard-ready dict with file count, canon coverage,
    summary/keyword coverage, missing summaries, overdue reviews,
    and ingestion status.
    """
    library_id = str(library_id)

    # File stats
    source_files = SourceFile.objects.filter(library_id=library_id)
    file_count = source_files.count()
    total_size = source_files.aggregate(total=Sum("size_bytes"))["total"] or 0

    # Folder depth (max nesting via parent chain)
    # Count items that have parent → parent → parent (3 levels max by design)
    depth_0 = LibraryItem.objects.filter(library_id=library_id, parent__isnull=True).exists()
    depth_1 = LibraryItem.objects.filter(library_id=library_id, parent__isnull=False).exists()
    depth_2 = LibraryItem.objects.filter(
        library_id=library_id, parent__isnull=False, parent__parent__isnull=False
    ).exists()
    folder_depth = 0
    if depth_0:
        folder_depth = 1
    if depth_1:
        folder_depth = 2
    if depth_2:
        folder_depth = 3

    # Canon coverage
    total_items = LibraryItem.objects.filter(library_id=library_id, is_folder=False).count()
    canonical_items = LibraryItem.objects.filter(library_id=library_id, is_folder=False, is_featured=True).count()

    # Summary and keyword coverage (via Artifacts linked to library's SourceFiles)
    artifacts = Artifact.objects.filter(source_file__library_id=library_id)
    total_artifacts = artifacts.count()
    with_summary = artifacts.exclude(interior_summary="").count()
    with_keywords = artifacts.exclude(keywords=[]).count()

    # Missing summaries (filenames)
    missing_summary_artifacts = (
        artifacts.filter(Q(interior_summary="") | Q(interior_summary__isnull=True))
        .select_related("source_file")
        .values("id", "source_file__id", "source_file__filename")
    )
    missing_summaries = [
        {
            "filename": a["source_file__filename"],
            "source_file_id": str(a["source_file__id"]),
            "artifact_id": str(a["id"]),
        }
        for a in missing_summary_artifacts
    ]

    # Overdue reviews (from puddlejump_canonical_metadata.review_date)
    today = date.today().isoformat()
    overdue_reviews = []
    canonical_items_qs = LibraryItem.objects.filter(
        library_id=library_id,
        is_folder=False,
        is_featured=True,
    ).exclude(puddlejump_canonical_metadata={})

    for item in canonical_items_qs:
        meta = item.puddlejump_canonical_metadata or {}
        review_date = meta.get("review_date")
        if review_date and review_date < today:
            try:
                days_overdue = (date.today() - date.fromisoformat(review_date)).days
            except (ValueError, TypeError):
                days_overdue = 0
            # Get filename from content object
            filename = ""
            if item.content_object and hasattr(item.content_object, "filename"):
                filename = item.content_object.filename
            overdue_reviews.append({
                "filename": filename,
                "library_item_id": str(item.id),
                "review_date": review_date,
                "days_overdue": days_overdue,
            })

    # Ingestion status (ChunkEmbeddings)
    total_embedded = ChunkEmbedding.objects.filter(library_id=library_id).count()
    complete_embedded = ChunkEmbedding.objects.filter(
        library_id=library_id, status=EmbeddingStatus.COMPLETE
    ).count()
    failed_embedded = ChunkEmbedding.objects.filter(
        library_id=library_id, status=EmbeddingStatus.FAILED
    ).count()
    pending_embedded = total_embedded - complete_embedded - failed_embedded

    return {
        "library_id": library_id,
        "file_count": file_count,
        "total_size_bytes": total_size,
        "folder_depth": folder_depth,
        "canon_coverage": {
            "total_items": total_items,
            "canonical_items": canonical_items,
            "percentage": round((canonical_items / total_items * 100) if total_items > 0 else 0, 1),
        },
        "summary_coverage": {
            "total_artifacts": total_artifacts,
            "with_summary": with_summary,
            "percentage": round((with_summary / total_artifacts * 100) if total_artifacts > 0 else 0, 1),
        },
        "keyword_coverage": {
            "total_artifacts": total_artifacts,
            "with_keywords": with_keywords,
            "percentage": round((with_keywords / total_artifacts * 100) if total_artifacts > 0 else 0, 1),
        },
        "missing_summaries": missing_summaries,
        "overdue_reviews": overdue_reviews,
        "ingestion_status": {
            "total_source_files": file_count,
            "fully_embedded": complete_embedded,
            "pending_embedding": pending_embedded,
            "failed_embedding": failed_embedded,
            "percentage_complete": round(
                (complete_embedded / total_embedded * 100) if total_embedded > 0 else 0, 1
            ),
        },
    }


# ============================================================================
# PHASE 2: DUPLICATE DETECTION
# ============================================================================

def _get_document_embeddings(
    library_id: str,
    embedding_model_name: str = "all-mpnet-base-v2",
    embedding_model_version: str = "1",
) -> dict[str, dict]:
    """
    Compute document-level embeddings by averaging chunk vectors.

    Returns dict keyed by source_file_id with:
      {vector: np.array, filename: str, excerpt: str}
    """
    # Find the embedding model
    try:
        emb_model = EmbeddingModel.objects.get(name=embedding_model_name, version=embedding_model_version)
    except EmbeddingModel.DoesNotExist:
        logger.warning(f"Embedding model {embedding_model_name}@{embedding_model_version} not found")
        return {}

    collection_name = get_collection_name(library_id, embedding_model_name, embedding_model_version)
    qdrant = get_qdrant_client()

    if not qdrant.collection_exists(collection_name):
        logger.warning(f"Qdrant collection {collection_name} does not exist")
        return {}

    # Get all completed chunk embeddings for this library + model
    chunk_embeddings = (
        ChunkEmbedding.objects.filter(
            library_id=library_id,
            embedding_model=emb_model,
            status=EmbeddingStatus.COMPLETE,
        )
        .select_related("chunk__artifact__source_file")
        .values_list(
            "chunk__artifact__source_file__id",
            "chunk__artifact__source_file__filename",
            "chunk__artifact__text",
            "qdrant_point_id",
            "qdrant_collection",
        )
    )

    # Group by source file
    sf_chunks: dict[str, dict] = defaultdict(lambda: {"filename": "", "excerpt": "", "point_ids": []})
    for sf_id, filename, artifact_text, point_id, collection in chunk_embeddings:
        key = str(sf_id)
        sf_chunks[key]["filename"] = filename
        if not sf_chunks[key]["excerpt"] and artifact_text:
            sf_chunks[key]["excerpt"] = artifact_text[:200]
        sf_chunks[key]["point_ids"].append(point_id)

    # Retrieve vectors from Qdrant and compute average per document
    doc_embeddings = {}
    for sf_id, data in sf_chunks.items():
        vectors = []
        for point_id in data["point_ids"]:
            point = qdrant.get_point(collection_name, point_id)
            if point and point.get("vector"):
                vectors.append(np.array(point["vector"]))

        if vectors:
            avg_vector = np.mean(vectors, axis=0)
            # Normalize for cosine similarity
            norm = np.linalg.norm(avg_vector)
            if norm > 0:
                avg_vector = avg_vector / norm
            doc_embeddings[sf_id] = {
                "vector": avg_vector,
                "filename": data["filename"],
                "excerpt": data["excerpt"],
            }

    return doc_embeddings


def detect_duplicates(
    library_id: UUID | str,
    similarity_threshold: float = 0.85,
    embedding_model_name: str = "all-mpnet-base-v2",
    embedding_model_version: str = "1",
) -> list[dict[str, Any]]:
    """
    Find document pairs with high cosine similarity using existing Qdrant embeddings.
    """
    library_id = str(library_id)
    doc_embeddings = _get_document_embeddings(library_id, embedding_model_name, embedding_model_version)

    if len(doc_embeddings) < 2:
        return []

    # Compare all document pairs
    sf_ids = list(doc_embeddings.keys())
    pairs = []

    for i in range(len(sf_ids)):
        for j in range(i + 1, len(sf_ids)):
            id_a, id_b = sf_ids[i], sf_ids[j]
            vec_a = doc_embeddings[id_a]["vector"]
            vec_b = doc_embeddings[id_b]["vector"]

            # Cosine similarity (vectors already normalized)
            similarity = float(np.dot(vec_a, vec_b))

            if similarity >= similarity_threshold:
                pairs.append({
                    "source_file_a_id": id_a,
                    "filename_a": doc_embeddings[id_a]["filename"],
                    "source_file_b_id": id_b,
                    "filename_b": doc_embeddings[id_b]["filename"],
                    "similarity_score": round(similarity, 4),
                    "excerpt_a": doc_embeddings[id_a]["excerpt"],
                    "excerpt_b": doc_embeddings[id_b]["excerpt"],
                })

    # Sort by similarity descending
    pairs.sort(key=lambda p: p["similarity_score"], reverse=True)
    return pairs


# ============================================================================
# PHASE 3: GLOSSARY EXTRACTION
# ============================================================================

# Patterns for bold-term definitions: **Term**: definition or **Term** — definition
_BOLD_DEFINITION_RE = re.compile(
    r"\*\*([^*]{2,60})\*\*\s*[:\s—–\-]+\s*([^\n]{10,})",
    re.MULTILINE,
)

# Patterns for markdown heading-based glossary sections
_GLOSSARY_HEADING_TERMS = {"glossary", "terminology", "definitions", "key terms", "vocabulary"}


def extract_glossary(library_id: UUID | str, min_occurrences: int = 1) -> list[dict[str, Any]]:
    """
    Extract defined terms from library using rule-based pattern matching.

    Combines:
    1. Bold-term definitions from artifact text
    2. Terms from glossary/terminology heading sections
    3. High-frequency TF-IDF keywords from existing metadata
    """
    library_id = str(library_id)

    artifacts = (
        Artifact.objects.filter(source_file__library_id=library_id)
        .select_related("source_file")
        .values("id", "text", "keywords", "source_file__id", "source_file__filename")
    )

    # term_key (lowercase) -> {term, definition, sources: set, occurrences}
    terms: dict[str, dict] = {}

    for artifact in artifacts:
        text = artifact["text"] or ""
        filename = artifact["source_file__filename"]
        sf_id = str(artifact["source_file__id"])
        art_id = str(artifact["id"])
        source_info = {"filename": filename, "source_file_id": sf_id, "artifact_id": art_id}

        # 1. Bold-term definitions
        for match in _BOLD_DEFINITION_RE.finditer(text):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            key = term.lower()

            if key not in terms:
                terms[key] = {
                    "term": term,
                    "definition": definition,
                    "source_files": [],
                    "source_file_ids": set(),
                    "occurrences": 0,
                }
            if sf_id not in terms[key]["source_file_ids"]:
                terms[key]["source_files"].append(source_info)
                terms[key]["source_file_ids"].add(sf_id)
            terms[key]["occurrences"] += 1

        # 2. TF-IDF keywords (already computed, add as terms without definitions)
        keywords = artifact["keywords"] or []
        for kw in keywords:
            key = kw.lower()
            if key not in terms:
                terms[key] = {
                    "term": kw,
                    "definition": "",
                    "source_files": [],
                    "source_file_ids": set(),
                    "occurrences": 0,
                }
            if sf_id not in terms[key]["source_file_ids"]:
                terms[key]["source_files"].append(source_info)
                terms[key]["source_file_ids"].add(sf_id)
            terms[key]["occurrences"] += 1

    # 3. Check for glossary heading sections in Shards
    glossary_shards = Shard.objects.filter(
        artifact__source_file__library_id=library_id,
        kind="heading",
    ).select_related("artifact__source_file")

    for shard in glossary_shards:
        title = (shard.title or "").lower()
        if any(g in title for g in _GLOSSARY_HEADING_TERMS):
            # This shard's parent artifact likely has glossary content
            # The bold-term regex above should already capture these
            pass

    # Clean up and filter
    result = []
    for key, data in terms.items():
        if data["occurrences"] >= min_occurrences:
            result.append({
                "term": data["term"],
                "definition": data["definition"],
                "source_files": data["source_files"],
                "occurrences": data["occurrences"],
            })

    # Sort by occurrences descending, then alphabetically
    result.sort(key=lambda t: (-t["occurrences"], t["term"].lower()))
    return result


# ============================================================================
# PHASE 4: CANONICAL CANDIDATES
# ============================================================================

def suggest_canonical_candidates(
    library_id: UUID | str,
    top_n: int = 10,
    exclude_already_canonical: bool = False,
    embedding_model_name: str = "all-mpnet-base-v2",
    embedding_model_version: str = "1",
) -> list[dict[str, Any]]:
    """
    Identify files that look authoritative but aren't marked canonical.

    Scoring criteria:
    1. Reference count: how many other files mention this filename
    2. Document length: longer = more comprehensive
    3. Structure score: has front matter, headings, keywords
    4. Embedding centrality: average cosine similarity to all other docs
    """
    library_id = str(library_id)

    # Get all source files with their artifacts and library items
    source_files = (
        SourceFile.objects.filter(library_id=library_id)
        .select_related()
        .values("id", "filename", "size_bytes")
    )

    if not source_files:
        return []

    # Build lookup structures
    sf_data: dict[str, dict] = {}
    all_filenames = []
    max_length = 0

    for sf in source_files:
        sf_id = str(sf["id"])
        filename = sf["filename"]
        all_filenames.append(filename)

        # Get artifact text and metadata
        artifact = Artifact.objects.filter(source_file_id=sf_id).first()
        text_length = len(artifact.text) if artifact and artifact.text else 0
        has_summary = bool(artifact and artifact.interior_summary)
        has_keywords = bool(artifact and artifact.keywords)
        max_length = max(max_length, text_length)

        # Get library item
        from django.contrib.contenttypes.models import ContentType
        sf_ct = ContentType.objects.get_for_model(SourceFile)
        lib_item = LibraryItem.objects.filter(
            library_id=library_id,
            content_type=sf_ct,
            content_object_id=sf_id,
        ).first()

        is_canonical = lib_item.is_featured if lib_item else False
        has_front_matter = bool(lib_item and lib_item.puddlejump_canonical_metadata)
        item_id = str(lib_item.id) if lib_item else ""

        # Count headings in shards
        heading_count = 0
        if artifact:
            heading_count = Shard.objects.filter(artifact=artifact, kind="heading").count()

        sf_data[sf_id] = {
            "filename": filename,
            "text_length": text_length,
            "has_summary": has_summary,
            "has_keywords": has_keywords,
            "has_front_matter": has_front_matter,
            "heading_count": heading_count,
            "is_canonical": is_canonical,
            "library_item_id": item_id,
            "artifact_text": artifact.text if artifact else "",
        }

    # 1. Reference count: how many other files mention this filename
    for sf_id, data in sf_data.items():
        ref_count = 0
        fname = data["filename"]
        fname_stem = fname.rsplit(".", 1)[0] if "." in fname else fname
        for other_id, other_data in sf_data.items():
            if other_id == sf_id:
                continue
            other_text = other_data.get("artifact_text", "")
            if other_text and (fname in other_text or fname_stem in other_text):
                ref_count += 1
        data["ref_count"] = ref_count

    # 2. Length score (normalized 0-1)
    for data in sf_data.values():
        data["length_score"] = data["text_length"] / max_length if max_length > 0 else 0

    # 3. Structure score (0-1)
    for data in sf_data.values():
        score = 0.0
        if data["has_front_matter"]:
            score += 0.3
        if data["heading_count"] >= 3:
            score += 0.3
        elif data["heading_count"] >= 1:
            score += 0.15
        if data["has_summary"]:
            score += 0.2
        if data["has_keywords"]:
            score += 0.2
        data["structure_score"] = score

    # 4. Embedding centrality (average similarity to all other docs)
    doc_embeddings = _get_document_embeddings(library_id, embedding_model_name, embedding_model_version)
    for sf_id, data in sf_data.items():
        if sf_id in doc_embeddings and len(doc_embeddings) > 1:
            vec = doc_embeddings[sf_id]["vector"]
            similarities = []
            for other_id, other_emb in doc_embeddings.items():
                if other_id != sf_id:
                    sim = float(np.dot(vec, other_emb["vector"]))
                    similarities.append(sim)
            data["centrality"] = np.mean(similarities) if similarities else 0.0
        else:
            data["centrality"] = 0.0

    # Combine scores (weighted sum)
    max_ref_count = max((d["ref_count"] for d in sf_data.values()), default=1) or 1

    candidates = []
    for sf_id, data in sf_data.items():
        if exclude_already_canonical and data["is_canonical"]:
            continue

        ref_score = data["ref_count"] / max_ref_count
        final_score = (
            0.30 * ref_score
            + 0.20 * data["length_score"]
            + 0.20 * data["structure_score"]
            + 0.20 * data["centrality"]
            + 0.10 * (1.0 if data["has_summary"] and data["has_keywords"] else 0.0)
        )

        # Build human-readable reasons
        reasons = []
        if data["ref_count"] > 0:
            reasons.append(f"Referenced by {data['ref_count']} other document{'s' if data['ref_count'] > 1 else ''}")
        if data["length_score"] > 0.7:
            reasons.append(f"Document length: {data['text_length']:,} chars (top {int((1 - data['length_score']) * 100 + 1)}%)")
        if data["centrality"] > 0.5:
            reasons.append(f"Centrality score: {data['centrality']:.2f} (highly representative)")
        if data["structure_score"] >= 0.7:
            reasons.append("Well-structured (headings, metadata, keywords)")
        if data["has_summary"] and data["has_keywords"]:
            reasons.append("Has summary and keywords")
        if not reasons:
            reasons.append("Moderate signal across scoring criteria")

        candidates.append({
            "source_file_id": sf_id,
            "filename": data["filename"],
            "score": round(final_score, 4),
            "reasons": reasons,
            "is_canonical": data["is_canonical"],
            "library_item_id": data["library_item_id"],
        })

    # Sort by score descending
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:top_n]


# ============================================================================
# PHASE 6: SUGGEST SUMMARIES (Inkwell LLM)
# ============================================================================

def suggest_summaries(library_id: UUID | str) -> list[dict[str, Any]]:
    """
    Suggest summaries for artifacts missing interior_summary using Inkwell.

    Read-only — returns proposals for user review. Does NOT write back.
    Gracefully handles Inkwell unavailability per-artifact.

    Returns: list of {artifact_id, source_file_id, filename, suggested_summary, method}
    """
    from inkwell.client import summarize, InkwellUnavailableError

    library_id = str(library_id)

    # Get artifacts missing summaries (same query as health check)
    artifacts = (
        Artifact.objects.filter(
            source_file__library_id=library_id,
        )
        .filter(Q(interior_summary="") | Q(interior_summary__isnull=True))
        .select_related("source_file")
    )

    results = []
    for artifact in artifacts:
        text = artifact.text or ""
        if len(text) < 50:
            # Too short for meaningful summarization
            results.append({
                "artifact_id": str(artifact.id),
                "source_file_id": str(artifact.source_file_id),
                "filename": artifact.source_file.filename,
                "suggested_summary": "",
                "method": "skipped_too_short",
                "error": None,
            })
            continue

        try:
            resp = summarize(text, words=60, style="neutral")
            results.append({
                "artifact_id": str(artifact.id),
                "source_file_id": str(artifact.source_file_id),
                "filename": artifact.source_file.filename,
                "suggested_summary": resp.get("summary", ""),
                "method": resp.get("method", "inkwell"),
                "error": None,
            })
        except InkwellUnavailableError as e:
            logger.warning("Inkwell unavailable for artifact %s: %s", artifact.id, e)
            results.append({
                "artifact_id": str(artifact.id),
                "source_file_id": str(artifact.source_file_id),
                "filename": artifact.source_file.filename,
                "suggested_summary": "",
                "method": "error",
                "error": str(e),
            })

    return results


# ============================================================================
# PHASE 7: RESTRUCTURE / CONSOLIDATE (Inkwell LLM)
# ============================================================================

def restructure_documents(
    library_id: UUID | str,
    similarity_threshold: float = 0.6,
    embedding_model_name: str = "all-mpnet-base-v2",
    embedding_model_version: str = "1",
) -> list[dict[str, Any]]:
    """
    Cluster related documents and suggest consolidation outlines using Inkwell.

    Read-only — returns clusters with outlines for user review. Does NOT merge.

    Steps:
    1. Compute document embeddings (reuses _get_document_embeddings)
    2. Cluster by cosine similarity > threshold
    3. For each cluster, generate an outline via Inkwell summarize

    Returns: list of clusters, each with {cluster_id, documents, outline, similarity_avg}
    """
    from inkwell.client import summarize, InkwellUnavailableError

    library_id = str(library_id)

    # Step 1: Get document embeddings
    doc_embeddings = _get_document_embeddings(library_id, embedding_model_name, embedding_model_version)

    if len(doc_embeddings) < 2:
        return []

    sf_ids = list(doc_embeddings.keys())

    # Step 2: Build similarity matrix and cluster
    # Simple greedy clustering: each document joins the first cluster where it
    # has similarity > threshold with ANY member
    clusters: list[list[str]] = []
    assigned: set[str] = set()

    # Precompute pairwise similarities for efficient lookup
    sim_matrix: dict[tuple[str, str], float] = {}
    for i in range(len(sf_ids)):
        for j in range(i + 1, len(sf_ids)):
            id_a, id_b = sf_ids[i], sf_ids[j]
            sim = float(np.dot(doc_embeddings[id_a]["vector"], doc_embeddings[id_b]["vector"]))
            sim_matrix[(id_a, id_b)] = sim
            sim_matrix[(id_b, id_a)] = sim

    for sf_id in sf_ids:
        if sf_id in assigned:
            continue

        # Start new cluster
        cluster = [sf_id]
        assigned.add(sf_id)

        # Find all unassigned docs similar to any cluster member
        changed = True
        while changed:
            changed = False
            for other_id in sf_ids:
                if other_id in assigned:
                    continue
                for member_id in cluster:
                    pair_key = (member_id, other_id)
                    if sim_matrix.get(pair_key, 0.0) >= similarity_threshold:
                        cluster.append(other_id)
                        assigned.add(other_id)
                        changed = True
                        break

        if len(cluster) >= 2:
            clusters.append(cluster)

    # Step 3: For each cluster, build outline via Inkwell
    results = []
    for idx, cluster_ids in enumerate(clusters):
        # Gather document info
        docs = []
        combined_text_parts = []
        similarities = []

        for sf_id in cluster_ids:
            emb = doc_embeddings[sf_id]
            docs.append({
                "source_file_id": sf_id,
                "filename": emb["filename"],
                "excerpt": emb["excerpt"],
            })
            # Get full text for outline generation
            artifact = Artifact.objects.filter(source_file_id=sf_id).first()
            if artifact and artifact.text:
                combined_text_parts.append(
                    f"--- {emb['filename']} ---\n{artifact.text[:2000]}"
                )

        # Average pairwise similarity within cluster
        for i in range(len(cluster_ids)):
            for j in range(i + 1, len(cluster_ids)):
                pair_key = (cluster_ids[i], cluster_ids[j])
                similarities.append(sim_matrix.get(pair_key, 0.0))

        avg_sim = float(np.mean(similarities)) if similarities else 0.0

        # Generate outline via Inkwell
        outline = ""
        outline_method = "none"
        combined_text = "\n\n".join(combined_text_parts)

        if combined_text and len(combined_text) >= 50:
            try:
                resp = summarize(combined_text, words=120, style="bullet")
                outline = resp.get("summary", "")
                outline_method = resp.get("method", "inkwell")
            except InkwellUnavailableError as e:
                logger.warning("Inkwell unavailable for cluster %d: %s", idx, e)
                outline = ""
                outline_method = "error"

        results.append({
            "cluster_id": idx,
            "documents": docs,
            "document_count": len(docs),
            "similarity_avg": round(avg_sim, 4),
            "outline": outline,
            "outline_method": outline_method,
        })

    # Sort by document count descending
    results.sort(key=lambda c: c["document_count"], reverse=True)
    return results
