from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from django.utils import timezone

from ops.models import OpsSnapshot

APPLICATION_COLLECTOR_VERSION = "1.0"
APPLICATION_SNAPSHOT_TTL_SECONDS = 120
APPLICATION_SERVER_NAME = "crossroads"
APPLICATION_SUBSYSTEM = "application"
DEFAULT_RABBITMQ_VHOST = "/crossroads"
COMMAND_TIMEOUT_SECONDS = 1.5


@dataclass
class ApplicationCollectionResult:
    status: str
    data: Dict[str, Any]
    errors: List[str]
    latency_ms: int
    collected_at: Any
    expires_at: Any


def _resolve_rabbitmq_vhost() -> str:
    explicit = os.getenv("OPS_RABBITMQ_VHOST")
    if explicit:
        return explicit
    broker_url = os.getenv("CELERY_BROKER_URL") or ""
    if broker_url:
        try:
            parsed = urlparse(broker_url)
            if parsed.path:
                return unquote(parsed.path.lstrip("/")) or "/"
        except ValueError:
            pass
    return DEFAULT_RABBITMQ_VHOST


def _run_command(argv: List[str]) -> Tuple[str, Optional[str]]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except FileNotFoundError:
        return "", "not_available"
    output = (result.stdout or "")[:64_000]
    if result.returncode != 0:
        return output, f"exit_{result.returncode}"
    return output, None


def collect_application_detail() -> ApplicationCollectionResult:
    start = monotonic()
    errors: List[str] = []
    rabbitmq_vhost = _resolve_rabbitmq_vhost()
    rabbitmq_connections = None
    celery_queue_messages = None

    output, err = _run_command(["rabbitmqctl", "list_connections", "-q", "-p", rabbitmq_vhost, "name"])
    if err:
        output, fallback_err = _run_command(["rabbitmqctl", "list_connections", "-q", "name"])
        if fallback_err:
            errors.append(f"rabbitmq_connections_{fallback_err}")
        else:
            errors.append("rabbitmq_connections_vhost_unsupported")
            rabbitmq_connections = len([line for line in output.splitlines() if line.strip()])
    else:
        rabbitmq_connections = len([line for line in output.splitlines() if line.strip()])

    output, err = _run_command(["rabbitmqctl", "list_queues", "-q", "-p", rabbitmq_vhost, "name", "messages"])
    if err:
        errors.append(f"rabbitmq_queues_{err}")
    else:
        total_messages = 0
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            queue_name = parts[0]
            try:
                message_count = int(parts[1])
            except ValueError:
                continue
            if "celery" in queue_name:
                total_messages += message_count
        celery_queue_messages = total_messages

    collected_at = timezone.now()
    expires_at = collected_at + timedelta(seconds=APPLICATION_SNAPSHOT_TTL_SECONDS)
    latency_ms = int((monotonic() - start) * 1000)
    status = "healthy" if not errors else "degraded"

    return ApplicationCollectionResult(
        status=status,
        data={
            "celery_queue_depth": celery_queue_messages,
            "rabbitmq_connection_count": rabbitmq_connections,
            "rabbitmq_vhost": rabbitmq_vhost,
        },
        errors=errors,
        latency_ms=latency_ms,
        collected_at=collected_at,
        expires_at=expires_at,
    )


def persist_application_snapshot(source: str = OpsSnapshot.SOURCE_SCHEDULED) -> OpsSnapshot:
    result = collect_application_detail()
    return OpsSnapshot.objects.create(
        server_name=APPLICATION_SERVER_NAME,
        subsystem=APPLICATION_SUBSYSTEM,
        status=result.status,
        collected_at=result.collected_at,
        expires_at=result.expires_at,
        collector_version=APPLICATION_COLLECTOR_VERSION,
        data=result.data,
        errors=result.errors,
        latency_ms=result.latency_ms,
        source=source,
    )


def latest_application_snapshot() -> OpsSnapshot | None:
    return (
        OpsSnapshot.objects.filter(
            server_name=APPLICATION_SERVER_NAME,
            subsystem=APPLICATION_SUBSYSTEM,
        )
        .order_by("-collected_at", "-updated_at")
        .first()
    )
