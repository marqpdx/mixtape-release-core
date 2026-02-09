# stackroom/api/puddlejump_utility_views.py

"""
Puddlejump Utility API Views

Endpoints for library analysis and maintenance utilities:
- Library Health dashboard metrics
- Duplicate detection via embeddings
- Glossary extraction via rule-based patterns
- Canonical candidate suggestions via heuristics
"""

from __future__ import annotations

import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication

from stackroom.models import Library
from stackroom.services.puddlejump_utilities import (
    get_library_health,
    detect_duplicates,
    extract_glossary,
    suggest_canonical_candidates,
)

logger = logging.getLogger(__name__)


def _verify_library_access(request, library_id: str) -> Library | None:
    """
    Verify the requesting user has access to the library.

    For now: user must be the sponsor of the library.
    Returns the library or None if access denied.
    """
    from django.contrib.contenttypes.models import ContentType

    user = request.user
    user_ct = ContentType.objects.get_for_model(user)

    library = Library.objects.filter(
        id=library_id,
        sponsor_content_type=user_ct,
        sponsor_object_id=str(user.pk),
    ).first()

    return library


class LibraryHealthView(APIView):
    """
    Get health metrics for a Puddlejump library.

    GET /api/stackroom/puddlejump/utilities/libraries/<library_id>/health/

    Returns dashboard-ready metrics: file count, canon coverage,
    summary/keyword coverage, missing summaries, overdue reviews,
    and ingestion status.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, library_id):
        library = _verify_library_access(request, str(library_id))
        if not library:
            return Response(
                {"error": "Library not found or access denied"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        try:
            health = get_library_health(library_id)
            return Response(health)
        except Exception as e:
            logger.error(f"Library health check failed for {library_id}: {e}", exc_info=True)
            return Response(
                {"error": f"Health check failed: {str(e)}"},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DuplicateDetectionView(APIView):
    """
    Detect near-duplicate documents in a library using embedding similarity.

    POST /api/stackroom/puddlejump/utilities/check-duplicates/

    Request body:
        {
            "library_id": "uuid",
            "similarity_threshold": 0.85  (optional, default 0.85)
        }

    Returns list of document pairs above the similarity threshold.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        library_id = request.data.get("library_id")
        if not library_id:
            return Response(
                {"error": "library_id is required"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        library = _verify_library_access(request, str(library_id))
        if not library:
            return Response(
                {"error": "Library not found or access denied"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        similarity_threshold = request.data.get("similarity_threshold", 0.85)
        try:
            similarity_threshold = float(similarity_threshold)
            if not (0.0 < similarity_threshold <= 1.0):
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "similarity_threshold must be a number between 0 and 1"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            pairs = detect_duplicates(library_id, similarity_threshold=similarity_threshold)
            return Response({
                "library_id": str(library_id),
                "similarity_threshold": similarity_threshold,
                "pair_count": len(pairs),
                "pairs": pairs,
            })
        except Exception as e:
            logger.error(f"Duplicate detection failed for {library_id}: {e}", exc_info=True)
            return Response(
                {"error": f"Duplicate detection failed: {str(e)}"},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GlossaryExtractionView(APIView):
    """
    Extract defined terms from a library using pattern matching.

    POST /api/stackroom/puddlejump/utilities/extract-glossary/

    Request body:
        {
            "library_id": "uuid",
            "min_occurrences": 1  (optional, default 1)
        }

    Returns list of terms with definitions, source files, and occurrence counts.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        library_id = request.data.get("library_id")
        if not library_id:
            return Response(
                {"error": "library_id is required"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        library = _verify_library_access(request, str(library_id))
        if not library:
            return Response(
                {"error": "Library not found or access denied"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        min_occurrences = request.data.get("min_occurrences", 1)
        try:
            min_occurrences = int(min_occurrences)
            if min_occurrences < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "min_occurrences must be a positive integer"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            terms = extract_glossary(library_id, min_occurrences=min_occurrences)
            return Response({
                "library_id": str(library_id),
                "min_occurrences": min_occurrences,
                "term_count": len(terms),
                "terms": terms,
            })
        except Exception as e:
            logger.error(f"Glossary extraction failed for {library_id}: {e}", exc_info=True)
            return Response(
                {"error": f"Glossary extraction failed: {str(e)}"},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CanonicalCandidatesView(APIView):
    """
    Suggest files that should be marked canonical based on heuristic scoring.

    POST /api/stackroom/puddlejump/utilities/suggest-canonical/

    Request body:
        {
            "library_id": "uuid",
            "top_n": 10  (optional, default 10),
            "exclude_already_canonical": false  (optional, default false)
        }

    Returns ranked list of candidate files with scores and reasons.
    """
    authentication_classes = [OAuth2Authentication, JWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        library_id = request.data.get("library_id")
        if not library_id:
            return Response(
                {"error": "library_id is required"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        library = _verify_library_access(request, str(library_id))
        if not library:
            return Response(
                {"error": "Library not found or access denied"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        top_n = request.data.get("top_n", 10)
        try:
            top_n = int(top_n)
            if top_n < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "top_n must be a positive integer"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        exclude_already_canonical = request.data.get("exclude_already_canonical", False)
        if isinstance(exclude_already_canonical, str):
            exclude_already_canonical = exclude_already_canonical.lower() in ("true", "1", "yes")

        try:
            candidates = suggest_canonical_candidates(
                library_id,
                top_n=top_n,
                exclude_already_canonical=exclude_already_canonical,
            )
            return Response({
                "library_id": str(library_id),
                "top_n": top_n,
                "exclude_already_canonical": exclude_already_canonical,
                "candidate_count": len(candidates),
                "candidates": candidates,
            })
        except Exception as e:
            logger.error(f"Canonical suggestion failed for {library_id}: {e}", exc_info=True)
            return Response(
                {"error": f"Canonical suggestion failed: {str(e)}"},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
