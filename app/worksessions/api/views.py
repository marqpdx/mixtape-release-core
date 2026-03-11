from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from worksessions import services
from worksessions.models import WorkSession

from .serializers import (
    SurfaceDocumentSaveSerializer,
    WorkSessionCreateSerializer,
    WorkSessionItemCreateSerializer,
    WorkSessionItemSerializer,
    WorkSessionSerializer,
    WritingSurfaceDocumentSerializer,
)


class WorkSessionListCreateView(generics.GenericAPIView):
    """
    GET  /api/work-sessions/           — List user's work sessions
    POST /api/work-sessions/           — Create a new work session
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sessions = WorkSession.objects.filter(
            owner=request.user,
            deleted_at__isnull=True,
        ).order_by("-started_at")

        serializer = WorkSessionSerializer(sessions, many=True)
        return Response(serializer.data)

    def post(self, request):
        ser = WorkSessionCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Resolve anchor
        model_name = ser.validated_data["anchor_content_type_model"].lower()
        object_id = ser.validated_data["anchor_object_id"]

        ct = ContentType.objects.filter(model=model_name).first()
        if ct is None:
            return Response(
                {"detail": f"Unknown content type: {model_name}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        model_class = ct.model_class()
        anchor = get_object_or_404(model_class, pk=object_id)

        session = services.create_work_session(
            owner=request.user,
            anchor_object=anchor,
        )

        return Response(
            WorkSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class WorkSessionDetailView(generics.GenericAPIView):
    """
    GET    /api/work-sessions/{id}/     — Session detail
    PATCH  /api/work-sessions/{id}/     — Update (e.g. end session)
    DELETE /api/work-sessions/{id}/     — Soft-delete
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, request, pk):
        return get_object_or_404(
            WorkSession,
            pk=pk,
            owner=request.user,
            deleted_at__isnull=True,
        )

    def get(self, request, pk):
        session = self._get_session(request, pk)
        return Response(WorkSessionSerializer(session).data)

    def patch(self, request, pk):
        session = self._get_session(request, pk)

        # Support ending a session
        if request.data.get("end", False):
            session = services.close_session(session)
            return Response(WorkSessionSerializer(session).data)

        return Response(WorkSessionSerializer(session).data)

    def delete(self, request, pk):
        session = self._get_session(request, pk)
        from django.utils import timezone

        session.deleted_at = timezone.now()
        session.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkSessionItemListCreateView(generics.GenericAPIView):
    """
    GET  /api/work-sessions/{id}/items/     — List session items
    POST /api/work-sessions/{id}/items/     — Add item
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, request, pk):
        return get_object_or_404(
            WorkSession,
            pk=pk,
            owner=request.user,
            deleted_at__isnull=True,
        )

    def get(self, request, pk):
        session = self._get_session(request, pk)
        items = session.items.filter(deleted_at__isnull=True).order_by("sequence")
        serializer = WorkSessionItemSerializer(items, many=True)
        return Response(serializer.data)

    def post(self, request, pk):
        session = self._get_session(request, pk)

        ser = WorkSessionItemCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        model_name = ser.validated_data["content_type_model"].lower()
        object_id = ser.validated_data["object_id"]

        ct = ContentType.objects.filter(model=model_name).first()
        if ct is None:
            return Response(
                {"detail": f"Unknown content type: {model_name}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        model_class = ct.model_class()
        artifact = get_object_or_404(model_class, pk=object_id)

        item = services.add_session_item(session, artifact)

        return Response(
            WorkSessionItemSerializer(item).data,
            status=status.HTTP_201_CREATED,
        )


class WorkSessionItemDeleteView(generics.GenericAPIView):
    """
    DELETE /api/work-sessions/{id}/items/{item_id}/    — Remove item
    """

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk, item_id):
        session = get_object_or_404(
            WorkSession,
            pk=pk,
            owner=request.user,
            deleted_at__isnull=True,
        )

        services.remove_session_item(session, item_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SurfaceDocumentView(generics.GenericAPIView):
    """
    GET /api/work-sessions/{id}/surface/    — Get surface document
    PUT /api/work-sessions/{id}/surface/    — Autosave surface document
    """

    permission_classes = [permissions.IsAuthenticated]

    def _get_session(self, request, pk):
        return get_object_or_404(
            WorkSession,
            pk=pk,
            owner=request.user,
            deleted_at__isnull=True,
        )

    def get(self, request, pk):
        session = self._get_session(request, pk)
        if session.surface_document is None:
            return Response(
                {"detail": "No surface document"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            WritingSurfaceDocumentSerializer(session.surface_document).data
        )

    def put(self, request, pk):
        session = self._get_session(request, pk)

        ser = SurfaceDocumentSaveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        services.save_surface_document(
            session=session,
            body_json=ser.validated_data["body_json"],
            client_session_id=ser.validated_data.get("client_session_id", ""),
        )

        return Response(
            WritingSurfaceDocumentSerializer(session.surface_document).data
        )


class CheckpointView(APIView):
    """
    POST /api/work-sessions/{id}/checkpoint/    — Trigger checkpoint extraction
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        session = get_object_or_404(
            WorkSession,
            pk=pk,
            owner=request.user,
            deleted_at__isnull=True,
        )

        extracted = services.checkpoint_extraction(session)

        return Response(
            {
                "extracted_count": len(extracted),
                "extracted": [
                    {"artifact_type": t, "artifact_id": str(i)}
                    for t, i in extracted
                ],
            }
        )
