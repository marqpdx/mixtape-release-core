# stackroom/api/views.py

from __future__ import annotations

import uuid
import hashlib
import json
import time
import logging
from django.db import transaction, connection, models
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated, AllowAny

from stackroom.models import (
    Library,
    SourceFile,
    IngestionRun,
    Artifact,
    Shard,
    Chunk,
    IngestionReceipt,
)
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from writing.models import WritingPiece
from groups.models import Group
from stackroom.api.auth import ServiceJWTAuthentication
from stackroom.api.permissions import HasStackroomIRScope
from stackroom.api.serializers import (
    IngestionStartSerializer,
    ArtifactCreateSerializer,
    ShardBulkSerializer,
    ChunkBulkSerializer,
    IngestionCompleteSerializer,
    FileUploadSerializer,
    FileUploadResponseSerializer,
    LibrarySerializer,
    LibraryCreateSerializer,
    LibraryUpdateSerializer,
)


def _guard_run_running(run: IngestionRun) -> Response | None:
    if run.status != "running":
        return Response(
            {"detail": "Ingestion run is not running.", "status": run.status},
            status=drf_status.HTTP_409_CONFLICT,
        )
    return None


class IngestionStartView(APIView):
    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasStackroomIRScope]

    @transaction.atomic
    def post(self, request):
        ser = IngestionStartSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        try:
            library = Library.objects.select_for_update().get(id=d["library_id"])
        except Library.DoesNotExist:
            return Response({"detail": "Library not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        sf, created = SourceFile.objects.get_or_create(
            library=library,
            hash_sha256=d["hash_sha256"],
            defaults={
                "origin": d["origin"],
                "path": d["path"],
                "filename": d["filename"],
                "content_type": d.get("content_type", "") or "",
                "size_bytes": d.get("size_bytes", 0) or 0,
                "git_commit": d.get("git_commit") or None,
                "source_url": d.get("source_url") or None,
                "created_by": request.user,
                "ir_version": d.get("ir_version", "0.1"),
            },
        )

        run = IngestionRun.objects.create(source_file=sf, status="running")

        return Response(
            {
                "ingestion_run_id": str(run.id),
                "source_file_id": str(sf.id),
                "source_file_created": created,
            },
            status=drf_status.HTTP_200_OK,
        )


class ArtifactCreateView(APIView):
    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasStackroomIRScope]

    @transaction.atomic
    def post(self, request):
        ser = ArtifactCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = get_object_or_404(IngestionRun.objects.select_for_update(), id=d["ingestion_run_id"])
        guard = _guard_run_running(run)
        if guard:
            return guard

        sf = get_object_or_404(SourceFile, id=d["source_file_id"])

        if run.source_file_id != sf.id:
            return Response({"detail": "run/source_file mismatch"}, status=drf_status.HTTP_400_BAD_REQUEST)

        art, created = Artifact.objects.get_or_create(
            source_file=sf,
            artifact_uid=d["artifact_uid"],
            defaults={
                "id": uuid.uuid4(),
                "artifact_type": d["artifact_type"],
                "format": d.get("format", "text/plain"),
                "text": d.get("text"),
                "storage_key": d.get("storage_key"),
                "ir_version": d.get("ir_version", sf.ir_version),
            },
        )

        # Idempotent update on retry
        if not created:
            Artifact.objects.filter(id=art.id).update(
                artifact_type=d["artifact_type"],
                format=d.get("format", art.format),
                text=d.get("text"),
                storage_key=d.get("storage_key"),
                ir_version=d.get("ir_version", art.ir_version),
                updated_at=timezone.now(),
            )

        if created:
            run.artifacts_created = run.artifacts_created + 1
            run.save(update_fields=["artifacts_created", "updated_at"])

        return Response(
            {"artifact_id": str(art.id), "artifact_created": created},
            status=drf_status.HTTP_200_OK,
        )


class ShardBulkUpsertView(APIView):
    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasStackroomIRScope]

    @transaction.atomic
    def post(self, request):
        ser = ShardBulkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = get_object_or_404(IngestionRun.objects.select_for_update(), id=d["ingestion_run_id"])
        guard = _guard_run_running(run)
        if guard:
            return guard

        art = get_object_or_404(Artifact, id=d["artifact_id"])

        if run.source_file_id != art.source_file_id:
            return Response({"detail": "run/artifact mismatch"}, status=drf_status.HTTP_400_BAD_REQUEST)

        id_map: dict[uuid.UUID, uuid.UUID | None] = {}
        shard_objs = []

        for s in d["shards"]:
            sid = s.get("id") or uuid.uuid4()
            id_map[sid] = s.get("parent_shard_id")
            shard_objs.append(
                Shard(
                    id=sid,
                    artifact=art,
                    kind=s["kind"],
                    level=s.get("level"),
                    title=s.get("title"),
                    text=s.get("text"),
                    order_index=s["order_index"],
                    parent_shard=None,
                    span=s["span"],
                )
            )

        # Accept client-stable IDs for idempotent retry
        Shard.objects.bulk_create(shard_objs, ignore_conflicts=True)

        for sid, parent_id in id_map.items():
            if parent_id:
                Shard.objects.filter(id=sid, artifact=art).update(parent_shard_id=parent_id)

        received = len(shard_objs)
        run.shards_extracted = run.shards_extracted + received
        run.save(update_fields=["shards_extracted", "updated_at"])

        return Response({"shards_received": received}, status=drf_status.HTTP_200_OK)


class ChunkBulkUpsertView(APIView):
    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasStackroomIRScope]

    @transaction.atomic
    def post(self, request):
        ser = ChunkBulkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = get_object_or_404(IngestionRun.objects.select_for_update(), id=d["ingestion_run_id"])
        guard = _guard_run_running(run)
        if guard:
            return guard

        art = get_object_or_404(Artifact, id=d["artifact_id"])

        if run.source_file_id != art.source_file_id:
            return Response({"detail": "run/artifact mismatch"}, status=drf_status.HTTP_400_BAD_REQUEST)

        created_count = 0
        updated_count = 0

        for c in d["chunks"]:
            obj, created = Chunk.objects.get_or_create(
                artifact=art,
                chunk_strategy=c.get("chunk_strategy", "sliding_window"),
                hash_sha256=c["hash_sha256"],
                ir_version=c.get("ir_version", art.ir_version),
                defaults={
                    "id": c.get("id") or uuid.uuid4(),
                    "text": c["text"],
                    "token_estimate": c.get("token_estimate", 0) or 0,
                    "order_index": c["order_index"],
                    "source_spans": c["source_spans"],
                    "embedding_id": c.get("embedding_id", "") or "",
                },
            )
            if created:
                created_count += 1
            else:
                Chunk.objects.filter(id=obj.id).update(
                    text=c["text"],
                    token_estimate=c.get("token_estimate", obj.token_estimate),
                    order_index=c["order_index"],
                    source_spans=c["source_spans"],
                    embedding_id=c.get("embedding_id", obj.embedding_id),
                    updated_at=timezone.now(),
                )
                updated_count += 1

        run.chunks_indexed = run.chunks_indexed + created_count
        run.save(update_fields=["chunks_indexed", "updated_at"])

        return Response(
            {
                "chunks_received": len(d["chunks"]),
                "chunks_created": created_count,
                "chunks_updated": updated_count,
            },
            status=drf_status.HTTP_200_OK,
        )


class IngestionCompleteView(APIView):
    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [IsAuthenticated, HasStackroomIRScope]

    @transaction.atomic
    def post(self, request):
        ser = IngestionCompleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = get_object_or_404(IngestionRun.objects.select_for_update(), id=d["ingestion_run_id"])

        # Idempotent: if already finished, return latest receipt payload.
        if run.finished_at:
            latest = run.receipts.order_by("-created_at").first()
            if latest:
                return Response(latest.payload, status=drf_status.HTTP_200_OK)

        run.status = d["status"]
        run.errors = d.get("errors", [])
        run.warnings = d.get("warnings", [])
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "errors", "warnings", "finished_at", "updated_at"])

        receipt_payload = {
            "source_file_id": str(run.source_file_id),
            "ingestion_run_id": str(run.id),
            "status": d["status"],
            "artifacts_created": run.artifacts_created,
            "shards_extracted": run.shards_extracted,
            "chunks_indexed": run.chunks_indexed,
            "errors": run.errors,
            "warnings": run.warnings,
            "next_actions": d.get("next_actions", []),
        }

        # Phase 1.2: keep exactly one receipt per run (retry-safe).
        IngestionReceipt.objects.update_or_create(
            run=run,
            defaults={"status": d["status"], "payload": receipt_payload},
        )

        return Response(receipt_payload, status=drf_status.HTTP_200_OK)


class RetrieveView(APIView):
    """
    Semantic retrieval endpoint.

    Contract-compliant retrieval:
    1. Query Qdrant for similar vectors
    2. Resolve IDs back to Django
    3. Enforce library isolation
    4. Return IR-derived content only

    Performance:
    - Results are cached for 10 minutes (configurable)
    - Cache key: hash(query, library_id, model, limit, score_threshold)
    - Cache hit = instant response, no Qdrant query

    POST /api/stackroom/retrieve/
    """
    permission_classes = [IsAuthenticated]

    # Cache configuration
    CACHE_TIMEOUT = 60 * 10  # 10 minutes (600 seconds)
    CACHE_KEY_PREFIX = "stackroom:retrieve:"

    def _generate_cache_key(self, validated_data: dict) -> str:
        """
        Generate a cache key from request parameters.

        Cache key includes:
        - query text
        - library_id
        - model_name
        - model_version
        - limit
        - score_threshold (if provided)
        - artifact_types (if provided)
        - source_file_ids (if provided)

        Returns:
            Cache key string like "stackroom:retrieve:<hash>"
        """
        cache_parts = {
            "query": validated_data["query"],
            "library_id": str(validated_data["library_id"]),
            "model_name": validated_data["model_name"],
            "model_version": validated_data["model_version"],
            "limit": validated_data["limit"],
            "score_threshold": validated_data.get("score_threshold"),
            "artifact_types": sorted(validated_data.get("artifact_types") or []),
            "source_file_ids": sorted([str(id) for id in (validated_data.get("source_file_ids") or [])]),
        }

        # Create deterministic JSON representation
        cache_str = json.dumps(cache_parts, sort_keys=True)

        # Hash for compact key
        cache_hash = hashlib.sha256(cache_str.encode()).hexdigest()[:16]

        return f"{self.CACHE_KEY_PREFIX}{cache_hash}"

    def post(self, request):
        from stackroom.api.serializers import (
            RetrieveRequestSerializer,
            RetrieveResponseSerializer,
        )
        from stackroom.models import EmbeddingModel, Chunk
        from stackroom.services.qdrant_naming import get_collection_name_from_models
        from stackroom.services.qdrant_client import get_qdrant_client
        from stackroom.services.embedding_provider import embed_texts
        from stackroom.services.bm25 import calculate_bm25_scores, combine_scores
        from stackroom.services.reranking import rerank_results

        # Start timing
        start_time = time.perf_counter()
        timing = {}

        # Validate request
        req_ser = RetrieveRequestSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)
        data = req_ser.validated_data

        # Check cache first
        cache_key = self._generate_cache_key(data)
        cached_response = cache.get(cache_key)

        if cached_response is not None:
            # Cache hit - return immediately (no timing for cached responses)
            return Response(cached_response, status=drf_status.HTTP_200_OK)

        # Get library
        library = get_object_or_404(Library, id=data["library_id"])

        # Get embedding model
        try:
            embedding_model = EmbeddingModel.objects.get(
                name=data["model_name"],
                version=data["model_version"],
            )
        except EmbeddingModel.DoesNotExist:
            return Response(
                {
                    "error": "model_not_found",
                    "detail": f"No results yet. This library is being indexed with {data['model_name']}. Please try again in a few minutes.",
                },
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        # Get collection name
        collection_name = get_collection_name_from_models(library, embedding_model)

        # Check if collection exists
        qdrant_client = get_qdrant_client()
        try:
            if not qdrant_client.collection_exists(collection_name):
                # Count how many chunks are pending embedding
                from stackroom.models import ChunkEmbedding, EmbeddingStatus
                pending_count = ChunkEmbedding.objects.filter(
                    library=library,
                    embedding_model=embedding_model,
                    status=EmbeddingStatus.PENDING,
                ).count()

                total_count = ChunkEmbedding.objects.filter(
                    library=library,
                    embedding_model=embedding_model,
                ).count()

                if pending_count > 0:
                    return Response(
                        {
                            "error": "indexing_in_progress",
                            "detail": f"No results yet. {pending_count} of {total_count} chunks are being indexed.",
                        },
                        status=drf_status.HTTP_200_OK,  # 200 with empty results
                    )
                else:
                    return Response(
                        {
                            "error": "no_embeddings",
                            "detail": "No indexed content available. Please upload documents to this library.",
                        },
                        status=drf_status.HTTP_404_NOT_FOUND,
                    )
        except Exception as e:
            return Response(
                {
                    "error": "search_unavailable",
                    "detail": "Search temporarily unavailable. Try again in a moment.",
                },
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Embed query
        embed_start = time.perf_counter()
        try:
            query_vectors = embed_texts(
                texts=[data["query"]],
                embedding_model=embedding_model,
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Embedding provider error: {str(e)}", exc_info=True)
            return Response(
                {
                    "error": "embedding_failed",
                    "detail": "Something went wrong. Our team has been notified.",
                },
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not query_vectors:
            return Response(
                {
                    "error": "embedding_failed",
                    "detail": "Something went wrong. Our team has been notified.",
                },
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        query_vector = query_vectors[0]
        timing["embed_ms"] = round((time.perf_counter() - embed_start) * 1000, 2)

        # Search Qdrant
        qdrant_start = time.perf_counter()
        try:
            qdrant_results = qdrant_client.search(
                collection_name=collection_name,
                vector=query_vector,
                limit=data["limit"],
                score_threshold=data.get("score_threshold"),
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Qdrant search error: {str(e)}", exc_info=True)
            return Response(
                {
                    "error": "search_unavailable",
                    "detail": "Search temporarily unavailable. Try again in a moment.",
                },
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        timing["qdrant_ms"] = round((time.perf_counter() - qdrant_start) * 1000, 2)

        # Resolve chunks from Django (enforce library isolation)
        resolve_start = time.perf_counter()
        chunk_ids = [r["chunk_id"] for r in qdrant_results]

        # Build base query with library isolation
        chunk_query = Chunk.objects.filter(
            id__in=chunk_ids,
            artifact__source_file__library=library,  # Enforce library isolation
        )

        # Apply artifact_type filter if provided
        if data.get("artifact_types"):
            chunk_query = chunk_query.filter(artifact__artifact_type__in=data["artifact_types"])

        # Apply source_file_ids filter if provided
        if data.get("source_file_ids"):
            chunk_query = chunk_query.filter(artifact__source_file__id__in=data["source_file_ids"])

        chunks = chunk_query.select_related(
            "artifact",
            "artifact__source_file",
        )

        # Build chunk lookup
        chunk_lookup = {str(c.id): c for c in chunks}
        timing["resolve_ms"] = round((time.perf_counter() - resolve_start) * 1000, 2)

        # Calculate BM25 scores for hybrid search
        bm25_start = time.perf_counter()
        bm25_scores = calculate_bm25_scores(
            query=data["query"],
            chunks=list(chunks),
        )
        timing["bm25_ms"] = round((time.perf_counter() - bm25_start) * 1000, 2)

        # Build results with hybrid scoring (semantic + BM25)
        results = []
        for qdrant_hit in qdrant_results:
            chunk_id_str = str(qdrant_hit["chunk_id"])
            chunk = chunk_lookup.get(chunk_id_str)

            if not chunk:
                # Chunk not found or library mismatch - skip
                continue

            # Get semantic score from Qdrant
            semantic_score = qdrant_hit["score"]

            # Get BM25 score (default to 0 if not found)
            bm25_score = bm25_scores.get(chunk_id_str, 0.0)

            # Combine semantic and BM25 scores (65% semantic + 35% BM25)
            # Slightly increased BM25 weight for better keyword matching
            hybrid_score = combine_scores(
                semantic_score=semantic_score,
                bm25_score=bm25_score,
                semantic_weight=0.65,
                bm25_weight=0.35,
            )

            # Get chunk_type from Qdrant payload
            chunk_type = qdrant_hit.get("chunk_type", "body")

            # Apply score adjustment based on chunk type
            # TOC chunks (lists/questions) are much less relevant than body text
            # Headings provide context but less detail than body
            if chunk_type == "toc":
                final_score = hybrid_score * 0.50  # 50% penalty for TOC (was 15%)
            elif chunk_type == "heading":
                final_score = hybrid_score * 0.85  # 15% penalty for headings (was 5%)
            else:
                final_score = hybrid_score  # No penalty for body text

            results.append({
                "chunk_id": chunk.id,
                "text": chunk.text,
                "score": final_score,
                "source_spans": chunk.source_spans,
                "artifact_id": chunk.artifact.id,
                "artifact_type": chunk.artifact.artifact_type,
                "source_file_id": chunk.artifact.source_file.id,
                "filename": chunk.artifact.source_file.filename,
                "path": chunk.artifact.source_file.path,
            })

        # Re-sort by final scores (descending)
        results.sort(key=lambda x: x["score"], reverse=True)

        # Apply cross-encoder re-ranking to top results (optional, expensive)
        # TEMPORARILY DISABLED: MPS crash issue with cross-encoder in Django process
        # TODO: Re-enable after fixing force_cpu for Django wsgi/asgi
        # if len(results) > 0:
        #     rerank_start = time.perf_counter()
        #     rerank_top_k = min(20, len(results))
        #     results = rerank_results(
        #         query=data["query"],
        #         results=results,
        #         top_k=rerank_top_k,
        #     )
        #     timing["rerank_ms"] = round((time.perf_counter() - rerank_start) * 1000, 2)

        # Calculate total timing
        timing["total_ms"] = round((time.perf_counter() - start_time) * 1000, 2)

        # Serialize response
        response_data = {
            "query": data["query"],
            "results": results,
            "model": f"{embedding_model.name}@{embedding_model.version}",
            "collection": collection_name,
            "timing": timing,
        }

        resp_ser = RetrieveResponseSerializer(data=response_data)
        resp_ser.is_valid(raise_exception=True)

        # Log query asynchronously for observability
        from stackroom.tasks.retrieval import log_query_async
        log_query_async.delay(
            library_id=str(library.id),
            user_id=request.user.id if request.user.is_authenticated else None,
            query_text=data["query"],
            embedding_model_id=str(embedding_model.id),
            limit=data["limit"],
            score_threshold=data.get("score_threshold"),
            artifact_types=data.get("artifact_types"),
            source_file_ids=[str(id) for id in data.get("source_file_ids", [])] if data.get("source_file_ids") else None,
            result_count=len(results),
            timing=timing,
        )

        # Store in cache for future requests
        cache.set(cache_key, resp_ser.validated_data, self.CACHE_TIMEOUT)

        return Response(resp_ser.validated_data, status=drf_status.HTTP_200_OK)


class HealthCheckView(APIView):
    """
    Health check endpoint for Stackroom service.

    Checks:
    - Django database connectivity
    - Qdrant vector database connectivity
    - System status

    GET /api/stackroom/health

    No authentication required (public health check).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Perform health checks and return status.

        Returns:
            200: All systems operational
            503: Service degraded or unavailable
        """
        from stackroom.services.qdrant_client import get_qdrant_client

        health_status = {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
            "checks": {},
        }

        overall_healthy = True

        # Check 1: Database connectivity
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            health_status["checks"]["database"] = {
                "status": "healthy",
                "message": "Database connection successful",
            }
        except Exception as e:
            health_status["checks"]["database"] = {
                "status": "unhealthy",
                "message": f"Database error: {str(e)}",
            }
            overall_healthy = False

        # Check 2: Qdrant connectivity
        try:
            qdrant_client = get_qdrant_client()
            # Simple ping to verify connectivity
            collections = qdrant_client.list_collections()

            health_status["checks"]["qdrant"] = {
                "status": "healthy",
                "message": f"Qdrant connection successful ({len(collections)} collections)",
                "collection_count": len(collections),
            }
        except Exception as e:
            health_status["checks"]["qdrant"] = {
                "status": "unhealthy",
                "message": f"Qdrant error: {str(e)}",
            }
            overall_healthy = False

        # Check 3: Stale embedding monitoring
        try:
            from stackroom.models import ChunkEmbedding, Chunk
            import hashlib

            # Get all complete embeddings
            complete_embeddings = ChunkEmbedding.objects.filter(
                status="complete"
            ).select_related("chunk")

            total_count = complete_embeddings.count()

            if total_count > 0:
                # Count stale embeddings (hash mismatch)
                stale_count = 0
                for ce in complete_embeddings:
                    current_hash = hashlib.sha256(ce.chunk.text.encode()).hexdigest()
                    if current_hash != ce.embedded_text_hash:
                        stale_count += 1

                stale_percentage = (stale_count / total_count) * 100

                # Stale embeddings are a warning, not a failure
                if stale_percentage > 10:
                    health_status["checks"]["embeddings"] = {
                        "status": "warning",
                        "message": f"{stale_percentage:.1f}% of embeddings are stale (threshold: 10%)",
                        "total_embeddings": total_count,
                        "stale_embeddings": stale_count,
                        "stale_percentage": round(stale_percentage, 2),
                    }
                else:
                    health_status["checks"]["embeddings"] = {
                        "status": "healthy",
                        "message": f"{stale_percentage:.1f}% of embeddings are stale",
                        "total_embeddings": total_count,
                        "stale_embeddings": stale_count,
                        "stale_percentage": round(stale_percentage, 2),
                    }
            else:
                health_status["checks"]["embeddings"] = {
                    "status": "healthy",
                    "message": "No embeddings yet",
                    "total_embeddings": 0,
                    "stale_embeddings": 0,
                    "stale_percentage": 0.0,
                }

        except Exception as e:
            health_status["checks"]["embeddings"] = {
                "status": "error",
                "message": f"Failed to check embeddings: {str(e)}",
            }
            # Don't mark overall health as degraded for embedding check failures

        # Set overall status
        if not overall_healthy:
            health_status["status"] = "degraded"
            return Response(health_status, status=drf_status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(health_status, status=drf_status.HTTP_200_OK)


class ArtifactContentView(APIView):
    """
    Fetch full text content of an artifact.

    GET /api/stackroom/artifacts/{artifact_id}/content

    Returns:
        200: { "text": "..." }
        404: Artifact not found
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, artifact_id):
        """
        Fetch artifact text content.

        Args:
            artifact_id: UUID of the artifact

        Returns:
            200: Artifact text content
            404: Artifact not found or user lacks access
        """
        try:
            artifact = Artifact.objects.select_related(
                'source_file__library'
            ).get(id=artifact_id)
        except Artifact.DoesNotExist:
            return Response(
                {"detail": "Artifact not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # TODO: Add permission check - verify user has access to the library
        # For now, assume authenticated users can access any artifact

        return Response(
            {"text": artifact.text or ""},
            status=drf_status.HTTP_200_OK
        )


class SourceFileContentView(APIView):
    """
    Fetch full text content of a source file's primary artifact.

    GET /api/stackroom/source-files/{source_file_id}/content

    Returns the text from the first normalized_markdown or extracted_text artifact.

    Returns:
        200: { "text": "..." }
        404: Source file or artifact not found
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, source_file_id):
        """
        Fetch source file text content from primary artifact.

        Args:
            source_file_id: UUID of the source file

        Returns:
            200: Source file text content
            404: Source file not found or no artifacts available
        """
        try:
            source_file = SourceFile.objects.select_related('library').get(id=source_file_id)
        except SourceFile.DoesNotExist:
            return Response(
                {"detail": "Source file not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # TODO: Add permission check - verify user has access to the library

        # Try to find normalized_markdown first, then extracted_text
        artifact = source_file.artifacts.filter(
            artifact_type__in=['normalized_markdown', 'extracted_text']
        ).order_by(
            models.Case(
                models.When(artifact_type='normalized_markdown', then=0),
                models.When(artifact_type='extracted_text', then=1),
                default=2,
                output_field=models.IntegerField(),
            )
        ).first()

        if not artifact:
            return Response(
                {"detail": "No text artifact available for this source file"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        return Response(
            {"text": artifact.text or ""},
            status=drf_status.HTTP_200_OK
        )


class FileUploadView(APIView):
    """
    Simplified file upload endpoint for direct user uploads.

    POST /api/stackroom/upload

    Accepts:
        - file: The uploaded file
        - library_id: Target library UUID

    Returns:
        - source_file_id: Created source file ID
        - ingestion_run_id: Created ingestion run ID
        - filename: Original filename
        - status: Upload status

    This endpoint handles the full ingestion pipeline:
    1. Store file metadata (SourceFile)
    2. Create ingestion run
    3. Extract text content
    4. Create artifact with extracted text
    5. Queue for chunking and embedding (async)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Handle file upload and ingestion.
        """
        serializer = FileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        library_id = serializer.validated_data['library_id']
        uploaded_file = serializer.validated_data['file']

        # Verify library exists and user has access
        try:
            library = Library.objects.get(id=library_id)
        except Library.DoesNotExist:
            return Response(
                {"detail": "Library not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # TODO: Add permission check - verify user has write access to library

        # Compute file hash
        file_content = uploaded_file.read()
        file_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file.seek(0)  # Reset file pointer

        # Check if file already exists in library
        existing_file = SourceFile.objects.filter(
            library=library,
            hash_sha256=file_hash
        ).first()

        if existing_file:
            return Response(
                {
                    "detail": "File already exists in library",
                    "source_file_id": str(existing_file.id),
                },
                status=drf_status.HTTP_409_CONFLICT
            )

        # Create SourceFile
        source_file = SourceFile.objects.create(
            library=library,
            origin="upload",
            path=uploaded_file.name,
            filename=uploaded_file.name,
            content_type=uploaded_file.content_type or 'application/octet-stream',
            size_bytes=uploaded_file.size,
            hash_sha256=file_hash,
            created_by=request.user if request.user.is_authenticated else None,
        )

        # Create IngestionRun
        ingestion_run = IngestionRun.objects.create(
            source_file=source_file,
            status="running",
        )

        # Extract text from file
        try:
            extracted_text = self._extract_text(uploaded_file, uploaded_file.name)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Text extraction failed for {uploaded_file.name}: {str(e)}")
            extracted_text = f"[Text extraction failed: {str(e)}]"

        # Create Artifact with extracted text
        artifact = Artifact.objects.create(
            source_file=source_file,
            artifact_uid=f"extracted_text_{file_hash[:16]}",
            artifact_type="extracted_text",
            format="text/plain",
            text=extracted_text,
        )

        # Create IngestionReceipt
        IngestionReceipt.objects.create(
            run=ingestion_run,
            status="success",
            payload={
                "source_file_id": str(source_file.id),
                "artifact_id": str(artifact.id),
                "extracted_length": len(extracted_text),
            },
        )

        # Queue chunking and embedding tasks asynchronously
        from stackroom.tasks.processing import process_artifact

        process_artifact.delay(
            artifact_id=str(artifact.id),
            model_name="all-mpnet-base-v2",
            model_version="1",
            provider="sentence-transformers",
        )

        # Note: Ingestion run status will be updated by the async task
        # Status remains "running" until chunking + embedding completes

        # Return response
        response_data = {
            "source_file_id": str(source_file.id),
            "ingestion_run_id": str(ingestion_run.id),
            "filename": uploaded_file.name,
            "status": "success",
        }

        response_serializer = FileUploadResponseSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.validated_data, status=drf_status.HTTP_201_CREATED)

    def _extract_text(self, file, filename: str) -> str:
        """
        Extract text content from uploaded file.

        Supports:
        - Plain text (.txt, .md, .json, .csv, .html)
        - PDF files (.pdf) - requires PyPDF2 or pdfplumber
        - Word documents (.docx) - requires python-docx

        Args:
            file: Uploaded file object
            filename: Original filename

        Returns:
            Extracted text content
        """
        import io

        file_extension = filename.lower().split('.')[-1]

        # Plain text files
        if file_extension in ['txt', 'md', 'json', 'csv', 'html', 'xml', 'yaml', 'yml']:
            try:
                content = file.read()
                # Try UTF-8 first, fall back to latin-1
                try:
                    return content.decode('utf-8')
                except UnicodeDecodeError:
                    return content.decode('latin-1', errors='ignore')
            finally:
                file.seek(0)

        # PDF files
        if file_extension == 'pdf':
            try:
                import PyPDF2
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
                text_parts = []
                for page in pdf_reader.pages:
                    text_parts.append(page.extract_text())
                return '\n\n'.join(text_parts)
            except ImportError:
                return "[PDF support requires PyPDF2 library]"
            except Exception as e:
                return f"[PDF extraction failed: {str(e)}]"
            finally:
                file.seek(0)

        # Word documents
        if file_extension in ['docx', 'doc']:
            try:
                import docx
                doc = docx.Document(io.BytesIO(file.read()))
                text_parts = [paragraph.text for paragraph in doc.paragraphs]
                return '\n\n'.join(text_parts)
            except ImportError:
                return "[Word document support requires python-docx library]"
            except Exception as e:
                return f"[Word document extraction failed: {str(e)}]"
            finally:
                file.seek(0)

        # Unsupported file type
        return f"[Unsupported file type: .{file_extension}]"


class LibraryListCreateView(APIView):
    """
    List all libraries accessible to the current user.

    GET /api/stackroom/libraries
    POST /api/stackroom/libraries

    Returns list of libraries the user can access, or creates a new library.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get all libraries accessible to user.

        For now, returns all libraries.
        TODO: Filter by user permissions/memberships.
        """
        libraries = Library.objects.all().order_by('-created_at')
        scope = request.query_params.get("scope")
        if scope:
            libraries = libraries.filter(scope=scope)

        sponsor_type = request.query_params.get("sponsor_type")
        sponsor_id = request.query_params.get("sponsor_id")
        sponsor_username = request.query_params.get("sponsor_username")
        if sponsor_type:
            if sponsor_type == "group" and sponsor_id:
                from groups.models import Group
                sponsor_ct = ContentType.objects.get_for_model(Group)
                libraries = libraries.filter(
                    sponsor_content_type=sponsor_ct,
                    sponsor_object_id=sponsor_id,
                )
            elif sponsor_type == "user":
                User = get_user_model()
                sponsor_ct = ContentType.objects.get_for_model(User)
                if sponsor_id:
                    libraries = libraries.filter(
                        sponsor_content_type=sponsor_ct,
                        sponsor_object_id=sponsor_id,
                    )
                elif sponsor_username:
                    try:
                        user = User.objects.get(username=sponsor_username)
                        libraries = libraries.filter(
                            sponsor_content_type=sponsor_ct,
                            sponsor_object_id=user.id,
                        )
                    except User.DoesNotExist:
                        libraries = libraries.none()

        serializer = LibrarySerializer(libraries, many=True)
        data = serializer.data
        return Response(data, status=drf_status.HTTP_200_OK)

    def post(self, request):
        """
        Create a new library.

        Request body:
            - tenant_type: str ("group" or "user")
            - tenant_id: str (UUID or int-as-string)
            - name: str (max 255 characters)

        Returns:
            201: Library created successfully
            400: Invalid request data
            409: Library with same tenant_type, tenant_id, and name already exists
        """
        serializer = LibraryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Map sponsor fields (serializer uses tenant_*, model uses sponsor_*)
        from django.contrib.contenttypes.models import ContentType

        # Get sponsor content type
        if data['tenant_type'] == 'group':
            from groups.models import Group
            sponsor_ct = ContentType.objects.get_for_model(Group)
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            sponsor_ct = ContentType.objects.get_for_model(User)

        # Check for existing library with same unique constraint
        # Model uses 'title' field, not 'name'
        existing = Library.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=data['tenant_id'],
            title=data['name'],
        ).first()

        if existing:
            return Response(
                {
                    "detail": "Library with this name already exists for this tenant",
                    "library_id": str(existing.id),
                },
                status=drf_status.HTTP_409_CONFLICT
            )

        # Create library
        # Map serializer fields to model fields
        library = Library.objects.create(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=data['tenant_id'],
            title=data['name'],  # Serializer uses 'name', model uses 'title'
            summary=data.get("summary", ""),
            body=data.get("body", ""),
            scope=data.get("scope", "general"),
            visibility=data.get("visibility", "private"),
            submitted_by=request.user,
        )

        # Return created library
        response_serializer = LibrarySerializer(library)
        return Response(response_serializer.data, status=drf_status.HTTP_201_CREATED)


class LibraryDetailView(APIView):
    """
    Get details for a specific library.

    GET /api/stackroom/libraries/{library_id}
    PATCH /api/stackroom/libraries/{library_id}
    PUT /api/stackroom/libraries/{library_id}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        """
        Get library by ID.
        """
        try:
            library = Library.objects.get(id=library_id)
        except Library.DoesNotExist:
            return Response(
                {"detail": "Library not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # TODO: Check user has access to this library

        serializer = LibrarySerializer(library)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)

    def patch(self, request, library_id):
        """
        Update (rename) a library.

        Request body:
            - name: str (new library name, max 255 characters)

        Returns:
            200: Library updated successfully
            400: Invalid request data
            404: Library not found
            409: Library with new name already exists for this tenant
        """
        serializer = LibraryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            library = Library.objects.get(id=library_id)
        except Library.DoesNotExist:
            return Response(
                {"detail": "Library not found"},
                status=drf_status.HTTP_404_NOT_FOUND
            )

        # TODO: Check user has write access to this library

        # Check for naming conflict with same sponsor
        # Model uses sponsor_content_type/sponsor_object_id and title, not tenant_*/name
        if "name" in data:
            existing = Library.objects.filter(
                sponsor_content_type=library.sponsor_content_type,
                sponsor_object_id=library.sponsor_object_id,
                title=data['name'],
            ).exclude(id=library_id).first()

            if existing:
                return Response(
                    {
                        "detail": "Library with this name already exists for this tenant",
                        "library_id": str(existing.id),
                    },
                    status=drf_status.HTTP_409_CONFLICT
                )

        # Update library title (serializer uses 'name', model uses 'title')
        if "name" in data:
            library.title = data['name']
        if "summary" in data:
            library.summary = data["summary"]
        if "body" in data:
            library.body = data["body"]
        if "visibility" in data:
            library.visibility = data["visibility"]
        library.save(update_fields=['title', 'summary', 'body', 'visibility', 'updated_at'])

        # Return updated library
        response_serializer = LibrarySerializer(library)
        return Response(response_serializer.data, status=drf_status.HTTP_200_OK)

    # Alias PUT to PATCH for convenience
    put = patch


class PublicLibraryListView(APIView):
    """
    Public library list for a user.

    GET /api/stackroom/libraries/public?username=<username>&scope=writing
    """
    permission_classes = [AllowAny]

    def get(self, request):
        username = request.query_params.get("username")
        if not username:
            return Response({"detail": "username is required"}, status=drf_status.HTTP_400_BAD_REQUEST)

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if not user:
            return Response([], status=drf_status.HTTP_200_OK)

        scope = request.query_params.get("scope")
        sponsor_ct = ContentType.objects.get_for_model(User)
        libraries = Library.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=user.id,
        )
        if scope:
            libraries = libraries.filter(scope=scope)

        allowed_visibility = ["public"]
        if request.user.is_authenticated:
            allowed_visibility.append("members")
        libraries = libraries.filter(visibility__in=allowed_visibility).order_by("-created_at")

        serializer = LibrarySerializer(libraries, many=True)
        return Response(serializer.data, status=drf_status.HTTP_200_OK)


class LibraryPlacementsView(APIView):
    """
    Public placements for a library (shelf).

    GET /api/stackroom/libraries/<uuid:library_id>/placements
    """
    permission_classes = [AllowAny]

    def get(self, request, library_id):
        library = get_object_or_404(Library, id=library_id)

        if library.visibility == "private":
            if not request.user.is_authenticated or library.sponsor != request.user:
                return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)
        if library.visibility == "members" and not request.user.is_authenticated:
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        ct_library = ContentType.objects.get_for_model(Library)
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        placements = ContentPlacement.objects.filter(
            target_content_type=ct_library,
            target_object_id=library.id,
            source_content_type=ct_piece,
            channel="shelf",
        ).order_by("order_index", "-created_at")

        user = request.user if request.user.is_authenticated else None
        results = []
        for placement in placements:
            if not can_view_placement(placement, user):
                continue
            try:
                payload = get_display_payload(placement)
            except Exception:
                continue

            piece = payload.get("source")
            if not piece or getattr(piece, "status", None) != "published":
                continue

            metadata = payload.get("metadata") or {}
            results.append(
                {
                    "id": str(placement.id),
                    "piece_id": str(piece.id),
                    "piece_slug": piece.slug,
                    "piece_title": metadata.get("title") or piece.title,
                    "piece_body_json": metadata.get("body_json") or piece.body_json,
                    "piece_status": piece.status,
                    "published_at": piece.published_at,
                    "visibility": placement.visibility,
                    "order_index": placement.order_index,
                    "created_at": placement.created_at,
                    "updated_at": placement.updated_at,
                    "display": {
                        "title": metadata.get("title"),
                        "excerpt": metadata.get("excerpt"),
                        "is_excerpt": metadata.get("is_excerpt"),
                        "body_json": metadata.get("body_json"),
                    },
                }
            )

        results.sort(
            key=lambda item: item["published_at"] or timezone.datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return Response(results, status=drf_status.HTTP_200_OK)


class LibraryPlacementsManageView(APIView):
    """
    Manage shelf placements (author-facing).

    POST /api/stackroom/libraries/<uuid:library_id>/placements
      body: { piece_id }

    DELETE /api/stackroom/libraries/<uuid:library_id>/placements/<uuid:placement_id>
    """
    permission_classes = [IsAuthenticated]

    def _can_edit_library(self, request, library: Library) -> bool:
        sponsor = library.sponsor
        if sponsor is None:
            return False
        if isinstance(sponsor, request.user.__class__):
            return sponsor == request.user
        if isinstance(sponsor, Group):
            if hasattr(sponsor, "can_user_post"):
                return sponsor.can_user_post(request.user)
        return False

    def post(self, request, library_id):
        library = get_object_or_404(Library, id=library_id)
        if not self._can_edit_library(request, library):
            return Response({"detail": "Forbidden"}, status=drf_status.HTTP_403_FORBIDDEN)

        piece_id = request.data.get("piece_id")
        if not piece_id:
            return Response({"detail": "piece_id is required"}, status=drf_status.HTTP_400_BAD_REQUEST)

        piece = get_object_or_404(WritingPiece, id=piece_id)
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        ct_library = ContentType.objects.get_for_model(Library)

        next_order = (
            ContentPlacement.objects.filter(
                target_content_type=ct_library,
                target_object_id=library.id,
                channel="shelf",
            ).aggregate(models.Max("order_index")).get("order_index__max") or 0
        ) + 1

        placement, _ = ContentPlacement.objects.update_or_create(
            source_content_type=ct_piece,
            source_object_id=piece.id,
            target_content_type=ct_library,
            target_object_id=library.id,
            channel="shelf",
            defaults={
                "placed_by": request.user,
                "visibility": library.visibility,
                "follow_updates": True,
                "order_index": next_order,
            },
        )

        return Response({"id": str(placement.id)}, status=drf_status.HTTP_201_CREATED)

    def delete(self, request, library_id, placement_id=None):
        library = get_object_or_404(Library, id=library_id)
        if not self._can_edit_library(request, library):
            return Response({"detail": "Forbidden"}, status=drf_status.HTTP_403_FORBIDDEN)

        placement = get_object_or_404(ContentPlacement, id=placement_id, target_object_id=library.id)
        placement.delete()
        return Response(status=drf_status.HTTP_204_NO_CONTENT)


class LibraryPlacementsReorderView(APIView):
    """
    Reorder placements within a shelf.

    POST /api/stackroom/libraries/<uuid:library_id>/placements/reorder
    body: { order: [placement_id, ...] }
    """
    permission_classes = [IsAuthenticated]

    def _can_edit_library(self, request, library: Library) -> bool:
        sponsor = library.sponsor
        if sponsor is None:
            return False
        if isinstance(sponsor, request.user.__class__):
            return sponsor == request.user
        if isinstance(sponsor, Group):
            if hasattr(sponsor, "can_user_post"):
                return sponsor.can_user_post(request.user)
        return False

    def post(self, request, library_id):
        library = get_object_or_404(Library, id=library_id)
        if not self._can_edit_library(request, library):
            return Response({"detail": "Forbidden"}, status=drf_status.HTTP_403_FORBIDDEN)

        order_list = request.data.get("order") or []
        if not isinstance(order_list, list):
            return Response({"detail": "order must be a list"}, status=drf_status.HTTP_400_BAD_REQUEST)

        for idx, placement_id in enumerate(order_list):
            ContentPlacement.objects.filter(
                id=placement_id,
                target_object_id=library.id,
                channel="shelf",
            ).update(order_index=idx + 1)

        return Response({"detail": "ok"}, status=drf_status.HTTP_200_OK)
