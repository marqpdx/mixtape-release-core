# surfaces/api/views.py
#
# The Argus Surface's REST endpoints (zz/api-sketch-argus-surface.md,
# puddlejump). Superuser-only throughout, same gate as the ops dashboard
# (ops.api.permissions.IsSuperuser).
#
# Blocks list/detail read Puddlejump's audit-blocks via PUDDLEJUMP_PATH
# (surfaces.services.argus_blocks) -- not configured on Crossroads today,
# so "available": false is the honest answer there until that's decided.
# Run series (create/get/stop) are fully real: nothing about them needs
# Cass. "Run now" is not: AC-5's path to Cass's Switchboard doesn't exist
# yet, so it always returns not_reachable, same stance the sketch
# describes, and records why on the ActionRun it still creates.

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from initiatives.models import (
    ActionRun,
    ActionRunInitiatorType,
    ActionRunStatus,
    Artifact,
    ArtifactKind,
    RunSeries,
    RunSeriesSpanKind,
    RunSeriesStatus,
)
from ops.api.permissions import IsSuperuser
from surfaces.api.serializers import CreateRunSeriesSerializer
from surfaces.services.argus_blocks import read_audit_block, read_audit_blocks
from surfaces.services.argus_initiatives import ensure_block_initiative

NOT_REACHABLE_REASON = "Cass is not reachable yet (AC-5 pending)."


def _active_series_id(block_slug: str) -> str | None:
    series = RunSeries.objects.filter(block_slug=block_slug, status=RunSeriesStatus.ACTIVE).first()
    return str(series.id) if series else None


def _findings_by_type(block_slug: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    artifacts = Artifact.objects.filter(kind=ArtifactKind.FINDINGS, structured_data__block_id=block_slug)
    for artifact in artifacts:
        for finding in (artifact.structured_data or {}).get("findings", []):
            counts[finding["type"]] = counts.get(finding["type"], 0) + 1
    return counts


def _serialize_run(run: ActionRun) -> dict:
    findings_artifact = run.artifacts.filter(kind=ArtifactKind.FINDINGS).first()
    return {
        "run_id": str(run.id),
        "started_at": run.started_at.isoformat(),
        "status": run.status,
        "findings": (findings_artifact.structured_data or {}).get("findings", []) if findings_artifact else [],
    }


def _serialize_series(series: RunSeries) -> dict:
    return {
        "series_id": str(series.id),
        "status": series.status,
        "block_slug": series.block_slug,
        "cadence_hours": series.cadence_hours,
        "span": {"kind": series.span_kind, "value": series.span_value},
        "per_turn_caps": series.per_turn_caps,
        "started_by": series.started_by.username if series.started_by else None,
        "runs_done": series.runs_done,
        "runs_total": series.runs_total,
        "day_of_span": series.day_of_span,
        "findings_count": series.findings_count,
    }


class ArgusBlockListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        blocks, reason = read_audit_blocks()
        if reason:
            return Response({"available": False, "reason": reason, "blocks": []})
        return Response({
            "available": True,
            "blocks": [
                {
                    "slug": block.slug,
                    "domain": block.domain,
                    "block_state": block.block_state,
                    "last_run_at": block.last_run_at,
                    "findings_by_type": _findings_by_type(block.slug),
                    "active_series_id": _active_series_id(block.slug),
                }
                for block in blocks
            ],
        })


class ArgusBlockDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request, slug):
        block, reason = read_audit_block(slug)
        if block is None:
            return Response({"available": False, "reason": reason}, status=status.HTTP_404_NOT_FOUND)

        initiative = ensure_block_initiative(slug, site_owner=request.user)
        runs = ActionRun.objects.filter(initiative=initiative, tool_name="argus.start_run").order_by("-started_at")
        return Response({
            "available": True,
            "slug": block.slug,
            "domain": block.domain,
            "block_state": block.block_state,
            "runs": [_serialize_run(run) for run in runs],
        })


class ArgusRunNowView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def post(self, request, slug):
        block, reason = read_audit_block(slug)
        if block is None:
            return Response({"available": False, "reason": reason}, status=status.HTTP_404_NOT_FOUND)

        initiative = ensure_block_initiative(slug, site_owner=request.user)
        ActionRun.objects.create(
            initiative=initiative,
            tool_name="argus.start_run",
            status=ActionRunStatus.FAILED,
            tenant_id=request.user.pk,
            tenant_namespace=getattr(settings, "SWITCHBOARD_DEFAULT_TENANT_NAMESPACE", "platform:crossroads"),
            initiator_type=ActionRunInitiatorType.HUMAN,
            initiator_id=str(request.user.pk),
            error_payload={"reason": "not_reachable", "detail": NOT_REACHABLE_REASON},
            completed_at=timezone.now(),
        )
        return Response({"status": "not_reachable", "detail": NOT_REACHABLE_REASON})


class ArgusRunSeriesListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def post(self, request):
        serializer = CreateRunSeriesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        initiative = ensure_block_initiative(data["block_slug"], site_owner=request.user)
        series = RunSeries(
            initiative=initiative,
            block_slug=data["block_slug"],
            cadence_hours=data["cadence_hours"],
            span_kind=data["span"]["kind"],
            span_value=data["span"]["value"],
            per_turn_caps=data.get("per_turn_caps") or {},
            started_by=request.user,
        )
        try:
            series.full_clean(exclude=["per_turn_caps"])
        except DjangoValidationError as exc:
            raise DRFValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
        series.save()
        return Response(_serialize_series(series), status=status.HTTP_201_CREATED)


class ArgusRunSeriesDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request, series_id):
        series = get_object_or_404(RunSeries, pk=series_id)
        return Response(_serialize_series(series))


class ArgusRunSeriesStopView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def post(self, request, series_id):
        series = get_object_or_404(RunSeries, pk=series_id)
        series.stop()
        return Response({"series_id": str(series.id), "status": series.status})
