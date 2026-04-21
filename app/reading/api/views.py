from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from writing.models import WritingPiece

from ..models import Dart, ReadingStats
from ..services import record_read, resolve_anchor


def _serialize_dart(dart, piece_body_json=None):
    anchor = resolve_anchor(dart, piece_body_json or {})
    return {
        "id": str(dart.id),
        "artifact_id": str(dart.artifact_id),
        "anchor_type": anchor["anchor_type"],
        "selected_text": anchor["selected_text"],
        "start": anchor["start"],
        "end": anchor["end"],
        "anchor_resolved": anchor["resolved"],
        "note_text": dart.note_text,
        "is_flagged": dart.is_flagged,
        "created_at": dart.created_at.isoformat(),
        "updated_at": dart.updated_at.isoformat(),
    }


def _serialize_stats(stats):
    return {
        "artifact_id": str(stats.artifact_id),
        "first_read_at": stats.first_read_at.isoformat() if stats.first_read_at else None,
        "last_read_at": stats.last_read_at.isoformat() if stats.last_read_at else None,
        "times_read": stats.times_read,
        "flagged_to_reread": stats.flagged_to_reread,
    }


class DartListCreateView(APIView):
    """
    GET  /api/reading/darts/?artifact_id=<uuid>  — list user's darts for a piece
    POST /api/reading/darts/                      — create a dart
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        artifact_id = request.query_params.get("artifact_id")
        if not artifact_id:
            return Response({"detail": "artifact_id required."}, status=400)
        piece = get_object_or_404(WritingPiece, id=artifact_id)
        darts = Dart.objects.filter(user=request.user, artifact=piece)
        return Response([_serialize_dart(d, piece.body_json) for d in darts])

    def post(self, request):
        artifact_id = request.data.get("artifact_id")
        if not artifact_id:
            return Response({"detail": "artifact_id required."}, status=400)
        piece = get_object_or_404(WritingPiece, id=artifact_id)

        anchor_type = request.data.get("anchor_type", Dart.ANCHOR_SELECTION)
        if anchor_type not in (Dart.ANCHOR_SELECTION, Dart.ANCHOR_DOCUMENT):
            return Response({"detail": "Invalid anchor_type."}, status=400)

        dart = Dart.objects.create(
            user=request.user,
            artifact=piece,
            anchor_type=anchor_type,
            selected_text=request.data.get("selected_text") or None,
            anchor_start_offset=request.data.get("anchor_start_offset", 0),
            anchor_end_offset=request.data.get("anchor_end_offset", 0),
            note_text=request.data.get("note_text", ""),
            is_flagged=bool(request.data.get("is_flagged", False)),
        )
        return Response(_serialize_dart(dart, piece.body_json), status=201)


class DartDetailView(APIView):
    """
    PATCH  /api/reading/darts/<uuid>/  — update note_text or is_flagged
    DELETE /api/reading/darts/<uuid>/  — delete
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_dart(self, request, dart_id):
        dart = get_object_or_404(Dart, id=dart_id)
        if dart.user_id != request.user.id:
            return None, Response({"detail": "Not found."}, status=404)
        return dart, None

    def patch(self, request, dart_id):
        dart, err = self._get_dart(request, dart_id)
        if err:
            return err
        if "note_text" in request.data:
            dart.note_text = request.data["note_text"]
        if "is_flagged" in request.data:
            dart.is_flagged = bool(request.data["is_flagged"])
        dart.save(update_fields=["note_text", "is_flagged", "updated_at"])
        return Response(_serialize_dart(dart, dart.artifact.body_json))

    def delete(self, request, dart_id):
        dart, err = self._get_dart(request, dart_id)
        if err:
            return err
        dart.delete()
        return Response(status=204)


class ReadingStatsView(APIView):
    """
    GET  /api/reading/stats/<artifact_id>/  — get or create reading stats for user + piece
    POST /api/reading/stats/<artifact_id>/record/  — record a read event
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, artifact_id):
        piece = get_object_or_404(WritingPiece, id=artifact_id)
        try:
            stats = ReadingStats.objects.get(user=request.user, artifact=piece)
            return Response(_serialize_stats(stats))
        except ReadingStats.DoesNotExist:
            return Response({
                "artifact_id": str(piece.id),
                "first_read_at": None,
                "last_read_at": None,
                "times_read": 0,
                "flagged_to_reread": False,
            })


class ReadingStatsRecordView(APIView):
    """
    POST /api/reading/stats/<artifact_id>/record/  — record a read event
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, artifact_id):
        piece = get_object_or_404(WritingPiece, id=artifact_id)
        stats = record_read(user=request.user, artifact=piece)
        return Response(_serialize_stats(stats))


class ReadingStatsFlagView(APIView):
    """
    POST /api/reading/stats/<artifact_id>/flag/  — toggle flagged_to_reread
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, artifact_id):
        piece = get_object_or_404(WritingPiece, id=artifact_id)
        stats, _ = ReadingStats.objects.get_or_create(user=request.user, artifact=piece)
        stats.flagged_to_reread = not stats.flagged_to_reread
        stats.save(update_fields=["flagged_to_reread", "updated_at"])
        return Response(_serialize_stats(stats))
