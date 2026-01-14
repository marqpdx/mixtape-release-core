# stackroom/api/collection_search.py

"""
Simple text search for Collections - searches Artifact content without embeddings.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q

from stackroom.models import Library, Artifact, Chunk


class CollectionTextSearchView(APIView):
    """
    Simple keyword search through Collection content.

    POST /api/collections/{collection_id}/search/

    Body:
        {
            "query": "search term",
            "limit": 20  // optional
        }

    Response:
        {
            "query": "search term",
            "results": [
                {
                    "source_file_id": "...",
                    "filename": "...",
                    "chunk_id": "...",
                    "chunk_text": "...highlighted...",
                    "chunk_index": 0
                }
            ],
            "total": 15
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, collection_id):
        """Search Collection content for keyword matches"""

        # Get library
        library = get_object_or_404(Library, id=collection_id)

        # Get query
        query = request.data.get('query', '').strip()
        limit = request.data.get('limit', 20)

        if not query:
            return Response(
                {"detail": "Query parameter required"},
                status=drf_status.HTTP_400_BAD_REQUEST
            )

        # Search through Chunks (already split text)
        chunks = Chunk.objects.filter(
            artifact__source_file__library=library,
            text__icontains=query  # Case-insensitive search
        ).select_related(
            'artifact__source_file'
        ).order_by(
            'artifact__source_file__filename',
            'chunk_index'
        )[:limit]

        # Format results
        results = []
        for chunk in chunks:
            # Get context snippet around match
            text = chunk.text
            query_lower = query.lower()
            text_lower = text.lower()

            # Find match position
            match_pos = text_lower.find(query_lower)
            if match_pos == -1:
                snippet = text[:200]
            else:
                # Extract context around match (±100 chars)
                start = max(0, match_pos - 100)
                end = min(len(text), match_pos + len(query) + 100)
                snippet = text[start:end]
                if start > 0:
                    snippet = '...' + snippet
                if end < len(text):
                    snippet = snippet + '...'

            results.append({
                'source_file_id': str(chunk.artifact.source_file.id),
                'filename': chunk.artifact.source_file.filename,
                'chunk_id': str(chunk.id),
                'chunk_text': snippet,
                'chunk_index': chunk.chunk_index,
            })

        return Response({
            'query': query,
            'results': results,
            'total': len(results),
        })
