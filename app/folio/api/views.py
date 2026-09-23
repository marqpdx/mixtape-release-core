# folio/api/views.py

import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inkwell.client import InkwellUnavailableError

from folio.models import Folio, FolioInception
from folio.services.gate1_parse import parse_gate1
from folio.services.gate2_extract import extract_gate2
from folio.services.gate3_classify import classify_gate3
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
    Runs the Hildegard pipeline. Phase 3 implements Gate 1 (deterministic
    surface parse, no LLM), Gate 2 (subject/intention extraction, local
    model via Inkwell), and Gate 3 (materiality classification, local
    model via Inkwell) — Gates 4-5 are not built yet, so there is no
    confirmed material-candidate structure to return. Debug trace
    (prototype spec §12) is prototype instrumentation, not permanent
    product data — not persisted, only returned in the response.
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
        gate1_latency_ms = round((time.monotonic() - start) * 1000, 2)

        gate2_output = None
        gate2_error = None
        start = time.monotonic()
        try:
            gate2_output = extract_gate2(inception.raw_text)
        except InkwellUnavailableError as exc:
            gate2_error = str(exc)
        gate2_latency_ms = round((time.monotonic() - start) * 1000, 2)

        gate3_output = None
        gate3_error = None
        start = time.monotonic()
        try:
            gate3_output = classify_gate3(inception.raw_text, gate1_output)
        except InkwellUnavailableError as exc:
            gate3_error = str(exc)
        gate3_latency_ms = round((time.monotonic() - start) * 1000, 2)

        if gate3_output is not None:
            status_value = "gate_3_complete"
        elif gate2_output is not None:
            status_value = "gate_3_unavailable"
        else:
            status_value = "gate_2_unavailable"
        payload = {"inception_id": str(inception.id), "status": status_value}

        is_dev = request.user.is_staff or request.user.is_superuser
        if request.query_params.get("debug") == "1" and is_dev:
            payload["debug"] = {
                "gate_1": {
                    "output": gate1_output,
                    "latency_ms": gate1_latency_ms,
                },
                "gate_2": {
                    "output": gate2_output,
                    "error": gate2_error,
                    "latency_ms": gate2_latency_ms,
                },
                "gate_3": {
                    "output": gate3_output,
                    "error": gate3_error,
                    "latency_ms": gate3_latency_ms,
                },
            }

        return Response(payload)
