# folio/api/views.py

import time

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inkwell.client import InkwellUnavailableError

from folio.models import CandidateStatus, Folio, FolioInception, FolioMaterialCandidate
from folio.services.gate1_parse import parse_gate1
from folio.services.gate2_extract import extract_gate2
from folio.services.gate3_classify import classify_gate3
from folio.services.gate4_normalize import build_candidates
from folio.services.gate5_validate import validate_candidates
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
    Runs the Hildegard pipeline. Phase 4 adds Gate 4 (deterministic display
    normalization) and Gate 5 (deterministic validation) on top of Gates
    1-3 — validated candidates are persisted as FolioMaterialCandidate rows
    with status=proposed, never confirmed automatically (prototype spec
    §8). Re-running analyze replaces only proposed candidates for this
    inception; anything a human has already confirmed/rejected/amended is
    left untouched, per the build plan guardrail that confirmed status is
    durable. Debug trace (prototype spec §12) is prototype instrumentation,
    not permanent product data — not persisted, only returned in the
    response.
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

        # Gate 3 failing to run (Inkwell unreachable) means this pass has no
        # trustworthy view of materiality — leave any previously persisted
        # proposed candidates untouched rather than replacing them with an
        # empty set. A transient outage must not look like "nothing found".
        persisted_count = None
        gate4_5_errors = []
        gate4_5_warnings = []
        gate4_5_latency_ms = 0.0
        if gate3_output is not None:
            start = time.monotonic()
            raw_candidates = build_candidates(inception.raw_text, gate2_output, gate3_output)
            validation = validate_candidates(inception.raw_text, raw_candidates, gate1_output)
            gate4_5_errors = validation["errors"]
            gate4_5_warnings = validation["warnings"]

            with transaction.atomic():
                FolioMaterialCandidate.objects.filter(
                    inception=inception, status=CandidateStatus.PROPOSED
                ).delete()
                new_candidates = [
                    FolioMaterialCandidate(inception=inception, status=CandidateStatus.PROPOSED, **candidate)
                    for candidate in validation["valid_candidates"]
                ]
                if new_candidates:
                    FolioMaterialCandidate.objects.bulk_create(new_candidates)
                persisted_count = len(new_candidates)
            gate4_5_latency_ms = round((time.monotonic() - start) * 1000, 2)

        if gate3_output is not None:
            status_value = "gate_5_complete"
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
                "gate_4_5": {
                    "candidates_persisted": persisted_count,
                    "skipped": gate3_output is None,
                    "errors": gate4_5_errors,
                    "warnings": gate4_5_warnings,
                    "latency_ms": gate4_5_latency_ms,
                },
            }

        return Response(payload)
