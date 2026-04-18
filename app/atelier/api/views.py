from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece

from ..services import compute_craft_readiness


class ReadinessView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, piece_slug):
        piece = get_object_or_404(WritingPiece, slug=piece_slug)
        if piece.author_id != request.user.id:
            return Response({"detail": "Not found."}, status=404)
        return Response(compute_craft_readiness(piece))
