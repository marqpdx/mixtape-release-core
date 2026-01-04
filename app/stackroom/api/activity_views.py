# stackroom/api/activity_views.py
"""
Activity & Statistics API Views

Provides dev/admin visibility into library activity:
- Ingestion runs (recent uploads, status, errors)
- Chunk statistics (counts, types, samples)
- Embedding statistics (models, success rate, pending)
- Search logs (recent queries, result counts, timing)
- Qdrant status (collections, vector counts)
"""

from __future__ import annotations

import logging
from django.db.models import Count, Q, Avg
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated

from stackroom.models import (
    Library,
    SourceFile,
    Artifact,
    Chunk,
    ChunkEmbedding,
    IngestionRun,
    EmbeddingModel,
)

logger = logging.getLogger(__name__)


class LibraryActivityView(APIView):
    """
    GET /api/stackroom/libraries/{library_id}/activity

    Returns comprehensive activity data for a library.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        """Get activity data for a library."""
        library = get_object_or_404(Library, id=library_id)

        # =================================================================
        # LIBRARY STATS
        # =================================================================
        files = SourceFile.objects.filter(library=library)
        artifacts = Artifact.objects.filter(source_file__library=library)
        chunks = Chunk.objects.filter(artifact__source_file__library=library)
        embeddings = ChunkEmbedding.objects.filter(library=library)

        library_stats = {
            "library_id": str(library.id),
            "library_name": library.name,
            "files_count": files.count(),
            "artifacts_count": artifacts.count(),
            "chunks_count": chunks.count(),
            "embeddings_count": embeddings.count(),
            "embeddings_pending": embeddings.filter(status='pending').count(),
            "embeddings_complete": embeddings.filter(status='complete').count(),
            "embeddings_failed": embeddings.filter(status='failed').count(),
        }

        # =================================================================
        # RECENT INGESTION RUNS (Last 10)
        # =================================================================
        recent_runs = IngestionRun.objects.filter(
            source_file__library=library
        ).order_by('-created_at')[:10]

        ingestion_runs = []
        for run in recent_runs:
            # Extract first error if exists
            first_error = run.errors[0] if run.errors else None

            ingestion_runs.append({
                "id": str(run.id),
                "source_file_id": str(run.source_file.id),
                "filename": run.source_file.filename,
                "status": run.status,
                "created_at": run.created_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "error": first_error,  # First error from errors JSONField
                "artifact_count": Artifact.objects.filter(source_file=run.source_file).count(),
            })

        # =================================================================
        # CHUNK TYPE DISTRIBUTION
        # =================================================================
        # Count chunks by type (extracted from source_spans metadata)
        chunk_type_counts = {"toc": 0, "heading": 0, "body": 0, "unknown": 0}
        for chunk in chunks[:1000]:  # Sample first 1000 chunks
            if chunk.source_spans and isinstance(chunk.source_spans, list) and len(chunk.source_spans) > 0:
                first_span = chunk.source_spans[0]
                if isinstance(first_span, dict):
                    chunk_type = first_span.get('chunk_type', 'unknown')
                    chunk_type_counts[chunk_type] = chunk_type_counts.get(chunk_type, 0) + 1
                else:
                    chunk_type_counts['unknown'] += 1
            else:
                chunk_type_counts['unknown'] += 1

        # =================================================================
        # SAMPLE CHUNKS (First 5 from each file)
        # =================================================================
        sample_chunks = []
        for file in files[:3]:  # First 3 files
            file_chunks = Chunk.objects.filter(
                artifact__source_file=file
            ).order_by('order_index')[:5]

            for chunk in file_chunks:
                chunk_type = 'unknown'
                if chunk.source_spans and isinstance(chunk.source_spans, list) and len(chunk.source_spans) > 0:
                    first_span = chunk.source_spans[0]
                    if isinstance(first_span, dict):
                        chunk_type = first_span.get('chunk_type', 'unknown')

                sample_chunks.append({
                    "chunk_id": str(chunk.id),
                    "filename": file.filename,
                    "chunk_type": chunk_type,
                    "order_index": chunk.order_index,
                    "text_preview": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,
                    "token_estimate": chunk.token_estimate,
                    "has_embedding": ChunkEmbedding.objects.filter(chunk=chunk).exists(),
                })

        # =================================================================
        # EMBEDDING MODELS USED
        # =================================================================
        embedding_models_used = embeddings.values(
            'embedding_model__name',
            'embedding_model__version',
            'embedding_model__dimensions'
        ).annotate(
            count=Count('id')
        ).order_by('-count')

        embedding_models = []
        for model_data in embedding_models_used:
            embedding_models.append({
                "name": model_data['embedding_model__name'],
                "version": model_data['embedding_model__version'],
                "dimensions": model_data['embedding_model__dimensions'],
                "embedding_count": model_data['count'],
            })

        # =================================================================
        # QDRANT STATUS (if available)
        # =================================================================
        qdrant_status = {"available": False, "collections": []}
        try:
            from stackroom.services.qdrant_client import get_qdrant_client

            qdrant = get_qdrant_client()

            # Check if Qdrant is reachable
            try:
                collections = qdrant.client.get_collections().collections
                qdrant_status["available"] = True

                # Find collections for this library
                library_id_str = str(library.id)
                for collection in collections:
                    if library_id_str in collection.name:
                        # Get collection info
                        collection_info = qdrant.client.get_collection(collection.name)
                        qdrant_status["collections"].append({
                            "name": collection.name,
                            "vectors_count": collection_info.vectors_count,
                            "points_count": collection_info.points_count,
                        })
            except Exception as e:
                logger.warning(f"Qdrant error: {e}")

        except Exception as e:
            logger.warning(f"Qdrant client error: {e}")

        # =================================================================
        # RESPONSE
        # =================================================================
        return Response({
            "library_stats": library_stats,
            "ingestion_runs": ingestion_runs,
            "chunk_type_distribution": chunk_type_counts,
            "sample_chunks": sample_chunks,
            "embedding_models": embedding_models,
            "qdrant_status": qdrant_status,
        }, status=drf_status.HTTP_200_OK)
