from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ops.api.permissions import IsSuperuser
from ops.api.serializers import OpsSummarySerializer, OpsTilesSerializer
from ops.services.snapshot import build_health_snapshot


def _no_cache_response(data):
    """Return a Response with no-cache headers to ensure fresh data."""
    response = Response(data)
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


class HealthSnapshotView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        snapshot = build_health_snapshot()
        return _no_cache_response(snapshot)


def _derive_overall_status(snapshot: dict) -> str:
    section_statuses = [
        snapshot.get("system", {}).get("status"),
        snapshot.get("disk", {}).get("status"),
        snapshot.get("network", {}).get("status"),
        snapshot.get("services", {}).get("status"),
        snapshot.get("application", {}).get("status"),
    ]
    services_data = snapshot.get("services", {}).get("data", {})
    backup_status = services_data.get("backups", {}).get("summary", {}).get("status")
    service_statuses = []
    for value in services_data.values():
        if isinstance(value, dict) and "status" in value:
            service_statuses.append(value.get("status"))
    if backup_status:
        service_statuses.append(backup_status)
    if any(status == "crit" for status in section_statuses):
        return "critical"
    if any(status == "critical" for status in service_statuses):
        return "critical"
    if any(status == "warn" for status in section_statuses):
        return "degraded"
    if any(status == "degraded" for status in service_statuses):
        return "degraded"
    return "healthy"


def _business_tile(title: str, status: str, detail: str, hint: str = "") -> dict:
    return {
        "title": title,
        "status": status,
        "detail": detail,
        "hint": hint,
    }


def _friendly_summary(snapshot: dict) -> dict:
    system = snapshot.get("system", {}).get("data", {})
    disk = snapshot.get("disk", {}).get("data", {})
    application = snapshot.get("application", {}).get("data", {})
    services = snapshot.get("services", {}).get("data", {})
    overall = _derive_overall_status(snapshot)
    backup_summary = services.get("backups", {}).get("summary", {})

    disk_free_pct = (disk.get("root") or {}).get("free_percent")
    swap_used = (system.get("swap_bytes") or {}).get("used")
    swap_total = (system.get("swap_bytes") or {}).get("total")
    swap_used_pct = (swap_used / swap_total * 100) if swap_total else 0

    rabbitmq_conn = application.get("rabbitmq_connection_count")
    celery_depth = application.get("celery_queue_depth")

    headline = "All systems look healthy."
    if overall == "degraded":
        headline = "Some systems need attention soon."
    if overall == "critical":
        headline = "Immediate attention needed."

    highlights = []
    if disk_free_pct is not None and disk_free_pct < 10:
        highlights.append("Low disk space on the server.")
    if swap_used_pct >= 20:
        highlights.append("Swap usage is elevated, which can slow the system.")
    if isinstance(celery_depth, int) and celery_depth >= 500:
        highlights.append("Background task queue is building up.")
    if isinstance(rabbitmq_conn, int) and rabbitmq_conn == 0:
        highlights.append("RabbitMQ has zero active connections.")
    if backup_summary.get("status") in ("degraded", "critical"):
        highlights.append("Backups need attention.")

    if not highlights:
        highlights.append("No urgent issues detected.")

    tiles = [
        _business_tile(
            "Core services",
            "healthy" if overall == "healthy" else ("degraded" if overall == "degraded" else "critical"),
            "API, workers, and message broker status.",
        ),
        _business_tile(
            "Storage",
            "degraded" if disk_free_pct is not None and disk_free_pct < 10 else "healthy",
            f"{disk_free_pct:.1f}% disk free" if disk_free_pct is not None else "Disk stats unavailable",
            "Keep 10%+ free to avoid outages.",
        ),
        _business_tile(
            "Background work",
            "degraded" if isinstance(celery_depth, int) and celery_depth >= 500 else "healthy",
            f"{celery_depth} tasks waiting" if celery_depth is not None else "Queue depth unavailable",
        ),
        _business_tile(
            "Backups",
            backup_summary.get("status", "healthy"),
            backup_summary.get("issues", [None])[0] or "Automated database and file backups.",
            "Timers wake daily; backup scripts may skip until 72h since the last successful archive.",
        ),
    ]

    return {
        "timestamp": snapshot.get("generated_at"),
        "overall_status": overall,
        "headline": headline,
        "highlights": highlights,
        "tiles": tiles,
    }


class OpsSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        snapshot = build_health_snapshot()
        summary = _friendly_summary(snapshot)
        serializer = OpsSummarySerializer(data=summary)
        serializer.is_valid(raise_exception=True)
        return _no_cache_response(serializer.data)


class OpsTilesView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        snapshot = build_health_snapshot()
        summary = _friendly_summary(snapshot)
        payload = {
            "timestamp": summary.get("timestamp"),
            "tiles": summary.get("tiles", []),
        }
        serializer = OpsTilesSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        return _no_cache_response(serializer.data)
