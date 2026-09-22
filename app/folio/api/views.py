# folio/api/views.py

import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from folio.models import Folio, FolioInception
from folio.services.gate1_parse import parse_gate1
from .serializers import FolioInceptionCreateSerializer, FolioInceptionSerializer


class FolioInceptionListCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = FolioInceptionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        raw_text = serializer.validated_data["raw_text"]
        title = serializer.validated_data.get("title", "")

        with transaction.atomic():
            folio = Folio.objects.create(title=title, created_by=request.user)
            inception = FolioInception.objects.create(
                folio=folio,
                raw_text=raw_text,
                created_by=request.user,
            )

        return Response(
            FolioInceptionSerializer(inception).data,
            status=status.HTTP_201_CREATED,
        )


class FolioInceptionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, inception_id):
        inception = get_object_or_404(
            FolioInception.objects.select_related("folio"),
            pk=inception_id,
            folio__created_by=request.user,
        )
        return Response(FolioInceptionSerializer(inception).data)


class FolioInceptionAnalyzeView(APIView):
    """
    Runs the Hildegard pipeline. Phase 1 only implements Gate 1
    (deterministic surface parse, no LLM) — Gates 2-5 are not built yet,
    so there is no confirmed material-candidate structure to return.
    Debug trace (prototype spec §12) is prototype instrumentation, not
    permanent product data — not persisted, only returned in the response.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, inception_id):
        inception = get_object_or_404(
            FolioInception,
            pk=inception_id,
            folio__created_by=request.user,
        )

        start = time.monotonic()
        gate1_output = parse_gate1(inception.raw_text)
        latency_ms = round((time.monotonic() - start) * 1000, 2)

        payload = {"inception_id": str(inception.id), "status": "gate_1_complete"}

        is_dev = request.user.is_staff or request.user.is_superuser
        if request.query_params.get("debug") == "1" and is_dev:
            payload["debug"] = {
                "gate_1": {
                    "output": gate1_output,
                    "latency_ms": latency_ms,
                },
            }

        return Response(payload)
