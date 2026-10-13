"""Piece-scoped, editor-only storage; capturing never modifies a manuscript."""

import json

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response

from writing.models import AtticEntry, WritingPiece
from writing.permissions import CanEditWritingPiece


class AtticEntrySerializer(serializers.ModelSerializer):
    # Client-generated IDs make retrying a timed-out capture idempotent.
    id = serializers.UUIDField()
    created_by_name = serializers.CharField(source="created_by.username", read_only=True, default="")

    class Meta:
        model = AtticEntry
        fields = ["id", "slice_json", "text", "source_title", "source_context", "created_at", "created_by_name"]
        read_only_fields = ["created_at", "created_by_name"]
        extra_kwargs = {
            "text": {"max_length": 200000},
            "source_context": {"max_length": 1000},
        }

    def validate_slice_json(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("content"), list) or not value["content"]:
            raise serializers.ValidationError("A non-empty formatted selection is required.")
        for edge in ("openStart", "openEnd"):
            depth = value.get(edge, 0)
            if type(depth) is not int or not 0 <= depth <= 32:
                raise serializers.ValidationError("Invalid selection depth.")
        if len(json.dumps(value).encode("utf-8")) > 1024 * 1024:
            raise serializers.ValidationError("Selection is too large (maximum 1 MB).")

        def validate_nodes(nodes, depth=0):
            if depth > 40 or not isinstance(nodes, list):
                raise serializers.ValidationError("Invalid selection structure.")
            for node in nodes:
                if not isinstance(node, dict) or not isinstance(node.get("type"), str):
                    raise serializers.ValidationError("Invalid selection node.")
                if "text" in node and not isinstance(node["text"], str):
                    raise serializers.ValidationError("Invalid selection text.")
                if "content" in node:
                    validate_nodes(node["content"], depth + 1)

        validate_nodes(value["content"])
        return value


class AtticEntryListCreateView(generics.ListCreateAPIView):
    serializer_class = AtticEntrySerializer
    permission_classes = [permissions.IsAuthenticated, CanEditWritingPiece]

    def get_piece(self):
        piece = get_object_or_404(WritingPiece, pk=self.kwargs["pk"], deleted_at__isnull=True)
        self.check_object_permissions(self.request, piece)
        return piece

    def get_queryset(self):
        return AtticEntry.objects.filter(piece=self.get_piece(), deleted_at__isnull=True).select_related("created_by")

    def create(self, request, *args, **kwargs):
        piece = self.get_piece()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entry, created = AtticEntry.objects.get_or_create(
            pk=data["id"],
            defaults={**data, "piece": piece, "created_by": request.user},
        )
        # Reusing an ID for different content must never overwrite an existing cutting.
        if not created and (
            entry.piece_id != piece.pk or entry.created_by_id != request.user.pk
            or entry.deleted_at is not None
            or any(getattr(entry, key) != value for key, value in data.items())
        ):
            return Response({"detail": "This capture ID is already in use."}, status=status.HTTP_409_CONFLICT)
        return Response(self.get_serializer(entry).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
