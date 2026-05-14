import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse

from django.utils import timezone as django_timezone

from ops.models import OpsSnapshot
from ops.services.application import latest_application_snapshot
from ops.services.postgres import latest_postgres_snapshot


SCHEMA_VERSION = "1.0"
SECTION_OK = "ok"
SECTION_WARN = "warn"
SECTION_CRIT = "crit"

DEFAULT_PER_CHECK_TIMEOUT = 0.25
DEFAULT_GLOBAL_BUDGET = 0.9
BACKUP_WARN_AGE_SECONDS = 36 * 3600
BACKUP_CRIT_AGE_SECONDS = 72 * 3600
APPLICATION_SURFACE_HTTP_TIMEOUT = 10.0
APPLICATION_SURFACE_PORT_TIMEOUT = 0.2

APPLICATION_SURFACES = {
    "mixtape-web": {
        "label": "Mixtape Web",
        "surface_type": "nextjs",
        "provider": "local-next",
        "environment": "local",
        "endpoint": "http://127.0.0.1:3011",
        "port": 3011,
        "probe_paths": ["/app/api/help/manifest"],
    },
    "crossroads-web": {
        "label": "Crossroads Web",
        "surface_type": "nextjs",
        "provider": "local-next",
        "environment": "local",
        "endpoint": "http://127.0.0.1:3010",
        "port": 3010,
        "probe_paths": ["/"],
    },
}


@dataclass
class CommandSpec:
    argv: List[str]
    timeout: float = DEFAULT_PER_CHECK_TIMEOUT
    max_output: int = 64_000


ALLOWLIST = {
    "ps_rss": CommandSpec(["ps", "-eo", "pid,comm,rss,pcpu,etimes", "--sort=-rss"]),
    "ps_cpu": CommandSpec(["ps", "-eo", "pid,comm,rss,pcpu,etimes", "--sort=-pcpu"]),
    "systemctl_show": CommandSpec(["systemctl", "show", "--no-page"]),
}


SERVICE_UNITS = {
    "django": "crossroads-api.service",
    "celery": "crossroads-celery.service",
    "inkwell": "crossroads-inkwell.service",
    "lanternmail": "crossroads-lanternmail.service",
    "livewire": "crossroads-livewire.service",
    "stackroom": "crossroads-stackroom.service",
    "seaweedfs": [
        "crossroads-seaweed-master.service",
        "crossroads-seaweed-volume.service",
        "crossroads-seaweed-filer.service",
        "crossroads-seaweed-s3.service",
    ],
    "nginx": "nginx.service",
    "postgres": ["postgresql@16-main.service", "postgresql.service"],
    "rabbitmq": "rabbitmq-server.service",
    "backups": [
        "pg-backup.service",
        "pg-backup.timer",
        "pg-backup-upload.service",
        "seaweed-backup.service",
        "seaweed-backup.timer",
        "seaweed-backup-upload.service",
    ],
}

def _now_iso() -> str:
    value = datetime.now(timezone.utc).isoformat()
    return value.replace("+00:00", "Z")


def _run_command(command: CommandSpec, extra_args: Optional[List[str]] = None) -> Tuple[str, Optional[str]]:
    argv = list(command.argv)
    if extra_args:
        argv.extend(extra_args)
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=command.timeout,
        )
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except FileNotFoundError:
        return "", "not_available"
    output = (result.stdout or "")[: command.max_output]
    if result.returncode != 0:
        return output, f"exit_{result.returncode}"
    return output, None


def _section_envelope(data: Any, errors: List[str], latency_ms: int) -> Dict[str, Any]:
    status = SECTION_OK
    if errors:
        status = SECTION_WARN
    return {
        "status": status,
        "latency_ms": latency_ms,
        "data": data,
        "errors": errors,
    }


def _section_envelope_with_status(
    *,
    status: str,
    data: Any,
    errors: List[str],
    latency_ms: int,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "status": status,
        "latency_ms": latency_ms,
        "data": data,
        "errors": errors,
    }
    if meta:
        payload.update(meta)
    return payload


def _read_file(path: str) -> Tuple[str, Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(), None
    except FileNotFoundError:
        return "", "not_available"
    except OSError:
        return "", "read_error"


def _parse_meminfo() -> Tuple[Dict[str, int], List[str]]:
    errors: List[str] = []
    text, err = _read_file("/proc/meminfo")
    if err:
        return {}, [err]
    meminfo: Dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            meminfo[key] = int(parts[0]) * 1024
        except ValueError:
            errors.append("meminfo_parse_error")
            break
    return meminfo, errors


def _parse_uptime() -> Tuple[Optional[float], List[str]]:
    text, err = _read_file("/proc/uptime")
    if err:
        return None, [err]
    try:
        uptime_seconds = float(text.split()[0])
        return uptime_seconds, []
    except (ValueError, IndexError):
        return None, ["uptime_parse_error"]


def _collect_system() -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    uptime_seconds, uptime_errors = _parse_uptime()
    errors.extend(uptime_errors)

    try:
        load_avg = os.getloadavg()
        load = {"1m": load_avg[0], "5m": load_avg[1], "15m": load_avg[2]}
    except OSError:
        load = {}
        errors.append("loadavg_unavailable")

    meminfo, mem_errors = _parse_meminfo()
    errors.extend(mem_errors)

    memory = {
        "total": meminfo.get("MemTotal"),
        "available": meminfo.get("MemAvailable"),
        "used": (meminfo.get("MemTotal") or 0) - (meminfo.get("MemAvailable") or 0),
    }
    swap = {
        "total": meminfo.get("SwapTotal"),
        "used": (meminfo.get("SwapTotal") or 0) - (meminfo.get("SwapFree") or 0),
    }

    return {
        "uptime_seconds": uptime_seconds,
        "load_average": load,
        "memory_bytes": memory,
        "swap_bytes": swap,
        "cpu_cores": os.cpu_count(),
    }, errors


def _parse_ps_table(output: str) -> List[Dict[str, Any]]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[1:]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, comm, rss, cpu, etimes = parts
        try:
            rows.append({
                "pid": int(pid),
                "command": comm,
                "rss_bytes": int(rss) * 1024,
                "cpu_percent": float(cpu),
                "elapsed_seconds": int(etimes),
            })
        except ValueError:
            continue
    return rows


def _collect_processes(limit: int = 10) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    rss_output, rss_error = _run_command(ALLOWLIST["ps_rss"])
    cpu_output, cpu_error = _run_command(ALLOWLIST["ps_cpu"])
    if rss_error:
        errors.append(f"ps_rss_{rss_error}")
    if cpu_error:
        errors.append(f"ps_cpu_{cpu_error}")
    rss_rows = _parse_ps_table(rss_output)[:limit]
    cpu_rows = _parse_ps_table(cpu_output)[:limit]
    return {
        "top_rss": rss_rows,
        "top_cpu": cpu_rows,
        "limit": limit,
    }, errors


def _collect_disk() -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    try:
        usage = shutil.disk_usage("/")
        statvfs = os.statvfs("/")
        inodes_total = statvfs.f_files
        inodes_free = statvfs.f_ffree
        inode_used = inodes_total - inodes_free if inodes_total else None
    except OSError:
        errors.append("disk_usage_error")
        return {}, errors

    return {
        "root": {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "free_percent": (usage.free / usage.total * 100) if usage.total else None,
        },
        "inodes": {
            "total": inodes_total,
            "used": inode_used,
            "free": inodes_free,
        },
        "io": {},
    }, errors


def _collect_network(max_ports: int = 10) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    tcp_text, tcp_err = _read_file("/proc/net/tcp")
    tcp6_text, tcp6_err = _read_file("/proc/net/tcp6")
    if tcp_err:
        errors.append(f"tcp_{tcp_err}")
    if tcp6_err:
        errors.append(f"tcp6_{tcp6_err}")

    connections = 0
    listen_ports: Dict[int, int] = {}

    def _parse_lines(text: str):
        nonlocal connections
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            connections += 1
            local_address = parts[1]
            state = parts[3]
            if state != "0A":
                continue
            if ":" not in local_address:
                continue
            _, port_hex = local_address.split(":")
            try:
                port = int(port_hex, 16)
            except ValueError:
                continue
            listen_ports[port] = listen_ports.get(port, 0) + 1

    if tcp_text:
        _parse_lines(tcp_text)
    if tcp6_text:
        _parse_lines(tcp6_text)

    top_ports = sorted(listen_ports.items(), key=lambda item: item[1], reverse=True)[:max_ports]
    if top_ports:
        errors.append("listening_process_unavailable")
    return {
        "tcp_connections": connections,
        "listening_port_count": len(listen_ports),
        "top_listening_ports": [
            {"port": port, "count": count, "process_name": None}
            for port, count in top_ports
        ],
    }, errors


def _parse_systemctl_show(output: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _parse_timestamp(value: Optional[str]) -> Optional[str]:
    if not value or value in ("n/a", "unknown"):
        return None
    return value


def _parse_monotonic_us(value: Optional[str]) -> Optional[int]:
    """Parse monotonic timestamp which can be microseconds or human-readable like '5h 1min 19.980440s'."""
    if not value:
        return None
    # Try parsing as raw microseconds first
    try:
        return int(value)
    except ValueError:
        pass
    # Parse human-readable format: "5d 2h 1min 19.980440s"
    import re
    total_us = 0
    patterns = [
        (r"(\d+)d", 86400 * 1_000_000),      # days
        (r"(\d+)h", 3600 * 1_000_000),        # hours
        (r"(\d+)min", 60 * 1_000_000),        # minutes
        (r"([\d.]+)s", 1_000_000),            # seconds (can have decimals)
    ]
    matched_any = False
    for pattern, multiplier in patterns:
        match = re.search(pattern, value)
        if match:
            matched_any = True
            num = float(match.group(1))
            total_us += int(num * multiplier)
    return total_us if matched_any else None


def _parse_memory_bytes(value: Optional[str]) -> Optional[int]:
    """Parse MemoryCurrent which can be a number, '[not set]', or empty."""
    if not value or value == "[not set]":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _collect_service_state(unit: str, uptime_seconds: Optional[float]) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    output, err = _run_command(
        ALLOWLIST["systemctl_show"],
        extra_args=[
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "ActiveEnterTimestamp",
            "-p",
            "ActiveEnterTimestampMonotonic",
            "-p",
            "Result",
            "-p",
            "LastTriggerUSec",
            "-p",
            "LastTriggerUSecMonotonic",
            "-p",
            "MainPID",
            "-p",
            "MemoryCurrent",
            unit,
        ],
    )
    if err:
        errors.append(f"systemctl_{err}")
        return {}, errors
    data = _parse_systemctl_show(output)
    active_monotonic = _parse_monotonic_us(data.get("ActiveEnterTimestampMonotonic"))
    uptime = None
    if active_monotonic is not None and uptime_seconds is not None:
        now_monotonic_us = int(uptime_seconds * 1_000_000)
        if now_monotonic_us >= active_monotonic:
            uptime = (now_monotonic_us - active_monotonic) / 1_000_000
    last_trigger_monotonic = _parse_monotonic_us(data.get("LastTriggerUSecMonotonic"))
    last_trigger_timestamp = _parse_timestamp(data.get("LastTriggerUSec"))
    last_trigger_age = None
    if last_trigger_monotonic is not None and uptime_seconds is not None:
        now_monotonic_us = int(uptime_seconds * 1_000_000)
        if now_monotonic_us >= last_trigger_monotonic:
            last_trigger_age = (now_monotonic_us - last_trigger_monotonic) / 1_000_000
    return {
        "active_state": data.get("ActiveState"),
        "sub_state": data.get("SubState"),
        "active_since": _parse_timestamp(data.get("ActiveEnterTimestamp")),
        "restart_timestamp": _parse_timestamp(data.get("ActiveEnterTimestamp")),
        "uptime_seconds": uptime,
        "last_trigger_timestamp": last_trigger_timestamp,
        "last_trigger_age_seconds": last_trigger_age,
        "result": data.get("Result"),
        "main_pid": data.get("MainPID"),
        "memory_bytes": _parse_memory_bytes(data.get("MemoryCurrent")),
    }, errors


def _collect_services(uptime_seconds: Optional[float]) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    services: Dict[str, Any] = {}

    for key, unit in SERVICE_UNITS.items():
        if isinstance(unit, list):
            unit_states: Dict[str, Any] = {}
            unit_errors: List[str] = []
            for subunit in unit:
                state, sub_errors = _collect_service_state(subunit, uptime_seconds)
                if sub_errors:
                    unit_errors.extend([f"{subunit}:{err}" for err in sub_errors])
                unit_states[subunit] = state
            services[key] = {
                "units": unit_states,
            }
            if unit_errors:
                errors.extend(unit_errors)
            continue

        state, state_errors = _collect_service_state(unit, uptime_seconds)
        if state_errors:
            errors.extend([f"{unit}:{err}" for err in state_errors])
        services[key] = state

    return services, errors


def _postgres_active_connections() -> Optional[int]:
    snapshot = latest_postgres_snapshot()
    if snapshot is None:
        return None
    connection_breakdown = (snapshot.data or {}).get("connection_breakdown") or {}
    active_connections = connection_breakdown.get("active")
    if isinstance(active_connections, int):
        return active_connections
    return None


def _application_from_snapshot() -> Dict[str, Any]:
    snapshot = latest_application_snapshot()
    postgres_connections = _postgres_active_connections()
    base_data = {"postgres_active_connections": postgres_connections}

    if snapshot is None:
        errors = ["snapshot_unavailable"]
        if postgres_connections is None:
            errors.append("postgres_snapshot_unavailable")
        return _section_envelope_with_status(
            status=SECTION_WARN,
            data=base_data,
            errors=errors,
            latency_ms=0,
            meta={"collected_at": None, "expires_at": None, "source": None},
        )

    now = django_timezone.now()
    is_stale = bool(snapshot.expires_at and snapshot.expires_at <= now)
    status = "stale" if is_stale else snapshot.status
    data = {**(snapshot.data or {}), "postgres_active_connections": postgres_connections}
    errors = list(snapshot.errors or [])
    if is_stale:
        errors = [*errors, "snapshot_stale"]
    if postgres_connections is None:
        errors = [*errors, "postgres_snapshot_unavailable"]

    return _section_envelope_with_status(
        status=status,
        data=data,
        errors=errors,
        latency_ms=snapshot.latency_ms or 0,
        meta={
            "collected_at": snapshot.collected_at.isoformat() if snapshot.collected_at else None,
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "source": snapshot.source,
        },
    )


def _postgres_detail_from_snapshot() -> Dict[str, Any]:
    snapshot = latest_postgres_snapshot()
    if snapshot is None:
        return _section_envelope_with_status(
            status=SECTION_WARN,
            data={},
            errors=["snapshot_unavailable"],
            latency_ms=0,
            meta={"collected_at": None, "expires_at": None, "source": None},
        )

    now = django_timezone.now()
    is_stale = bool(snapshot.expires_at and snapshot.expires_at <= now)
    status = "stale" if is_stale else snapshot.status
    errors = list(snapshot.errors or [])
    if is_stale:
        errors = [*errors, "snapshot_stale"]

    return _section_envelope_with_status(
        status=status,
        data=snapshot.data or {},
        errors=errors,
        latency_ms=snapshot.latency_ms or 0,
        meta={
            "collected_at": snapshot.collected_at.isoformat() if snapshot.collected_at else None,
            "expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "source": snapshot.source,
        },
    )


def _surface_status_from_http(http_status: Optional[int], port_open: bool) -> str:
    if not port_open:
        return "critical"
    if http_status is None:
        return "degraded"
    if 200 <= http_status < 400 or http_status in (401, 403):
        return "healthy"
    if http_status >= 500:
        return "critical"
    return "degraded"


def _probe_port(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=APPLICATION_SURFACE_PORT_TIMEOUT):
            return True
    except OSError:
        return False


def _probe_http(url: str) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    start = time.monotonic()
    request = urllib_request.Request(
        url,
        headers={"User-Agent": "crossroads-ops-snapshot/1.0"},
    )
    try:
        with urllib_request.urlopen(request, timeout=APPLICATION_SURFACE_HTTP_TIMEOUT) as response:
            latency_ms = int((time.monotonic() - start) * 1000)
            return response.getcode(), latency_ms, None
    except urllib_error.HTTPError as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        return exc.code, latency_ms, f"http_{exc.code}"
    except urllib_error.URLError:
        return None, None, "connection_error"
    except TimeoutError:
        return None, None, "timeout"


def _collect_application_surfaces() -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    surfaces: Dict[str, Any] = {}

    for surface_key, config in APPLICATION_SURFACES.items():
        endpoint = config["endpoint"]
        port = config["port"]
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port_open = _probe_port(host, port)
        probe_rows: List[Dict[str, Any]] = []
        surface_errors: List[str] = []
        surface_statuses: List[str] = []

        for probe_path in config.get("probe_paths", ["/"]):
            probe_url = f"{endpoint.rstrip('/')}{probe_path}"
            http_status, latency_ms, probe_error = _probe_http(probe_url)
            probe_status = _surface_status_from_http(http_status, port_open)
            surface_statuses.append(probe_status)
            probe_rows.append({
                "name": probe_path.strip("/") or "root",
                "url": probe_url,
                "status": probe_status,
                "http_status": http_status,
                "latency_ms": latency_ms,
                "detail": probe_error,
            })
            if probe_error:
                surface_errors.append(probe_error)

        if not port_open:
            surface_errors.append("port_unreachable")

        surface_status = "healthy"
        if any(status == "critical" for status in surface_statuses):
            surface_status = "critical"
        elif any(status == "degraded" for status in surface_statuses):
            surface_status = "degraded"

        if not probe_rows:
            summary_headline = "No probes configured"
            summary_detail = "This surface does not yet define any health probes."
        elif surface_status == "healthy":
            summary_headline = "Surface reachable"
            summary_detail = f"{port} responding normally"
        elif port_open:
            summary_headline = "Probe returned warnings"
            summary_detail = f"{port} reachable but HTTP probe needs attention"
        else:
            summary_headline = "Surface unreachable"
            summary_detail = f"No response on {port}"

        surfaces[surface_key] = {
            "label": config["label"],
            "surface_type": config["surface_type"],
            "provider": config["provider"],
            "environment": config["environment"],
            "status": surface_status,
            "endpoint": endpoint,
            "summary": {
                "headline": summary_headline,
                "detail": summary_detail,
            },
            "probes": probe_rows,
            "runtime": {
                "process_detected": port_open,
                "port": port,
            },
            "notes": ["Local development surface probe"],
            "errors": surface_errors,
        }
        if surface_errors:
            errors.extend([f"{surface_key}:{error}" for error in surface_errors])

    return {"surfaces": surfaces}, errors


def _application_surfaces_section() -> Dict[str, Any]:
    start = time.monotonic()
    collected_at = django_timezone.now().isoformat()
    data, errors = _collect_application_surfaces()
    surface_values = list((data.get("surfaces") or {}).values())
    status = "healthy"
    if any(surface.get("status") == "critical" for surface in surface_values):
        status = "critical"
    elif any(surface.get("status") == "degraded" for surface in surface_values):
        status = "degraded"
    latency_ms = int((time.monotonic() - start) * 1000)
    return _section_envelope_with_status(
        status=status,
        data=data,
        errors=errors,
        latency_ms=latency_ms,
        meta={
            "collected_at": collected_at,
            "expires_at": None,
            "source": "live",
        },
    )


def _ownership_profile() -> Dict[str, Dict[str, str]]:
    return {
        "inkwell": {
            "primary_resource": "memory-dominant",
            "burst_tolerance": "high",
            "starvation_sensitivity": "moderate",
            "recovery": "auto-recovering",
            "blast_radius": "platform",
        },
        "postgres": {
            "primary_resource": "disk-io",
            "burst_tolerance": "low",
            "starvation_sensitivity": "critical",
            "recovery": "requires-intervention",
            "blast_radius": "platform",
        },
        "celery": {
            "primary_resource": "cpu-bound",
            "burst_tolerance": "medium",
            "starvation_sensitivity": "moderate",
            "recovery": "auto-recovering",
            "blast_radius": "subsystem",
        },
        "rabbitmq": {
            "primary_resource": "memory-dominant",
            "burst_tolerance": "medium",
            "starvation_sensitivity": "high",
            "recovery": "auto-recovering",
            "blast_radius": "platform",
        },
        "seaweedfs": {
            "primary_resource": "disk-io",
            "burst_tolerance": "high",
            "starvation_sensitivity": "low",
            "recovery": "auto-recovering",
            "blast_radius": "subsystem",
        },
        "nginx": {
            "primary_resource": "network-bursty",
            "burst_tolerance": "high",
            "starvation_sensitivity": "moderate",
            "recovery": "auto-recovering",
            "blast_radius": "subsystem",
        },
    }


def _derive_service_status(service_state: Dict[str, Any]) -> str:
    active = service_state.get("active_state")
    if active == "active":
        return "healthy"
    if active in ("inactive", "failed"):
        return "critical"
    return "degraded"


def _derive_pressure(
    service_key: str,
    service_state: Dict[str, Any],
    system_data: Dict[str, Any],
    disk_data: Dict[str, Any],
    application_data: Dict[str, Any],
) -> str:
    if service_state.get("active_state") in ("inactive", "failed"):
        return "critical"
    memory = system_data.get("memory_bytes") or {}
    swap = system_data.get("swap_bytes") or {}
    mem_total = memory.get("total") or 0
    mem_available = memory.get("available") or 0
    swap_total = swap.get("total") or 0
    swap_used = swap.get("used") or 0
    mem_used_pct = ((mem_total - mem_available) / mem_total * 100) if mem_total else 0
    swap_used_pct = (swap_used / swap_total * 100) if swap_total else 0

    disk_root = (disk_data.get("root") or {})
    disk_free_pct = disk_root.get("free_percent") or 100

    if swap_used_pct >= 50:
        return "critical"
    if swap_used_pct >= 20 or mem_used_pct >= 90 or disk_free_pct <= 5:
        return "concerning"

    if service_key == "rabbitmq":
        queue_depth = application_data.get("celery_queue_depth")
        if isinstance(queue_depth, int) and queue_depth >= 2000:
            return "critical"
        if isinstance(queue_depth, int) and queue_depth >= 500:
            return "concerning"

    if service_key == "postgres":
        active_conns = application_data.get("postgres_active_connections")
        if isinstance(active_conns, int) and active_conns >= 200:
            return "concerning"

    return "expected"


def _annotate_services(
    services: Dict[str, Any],
    system_data: Dict[str, Any],
    disk_data: Dict[str, Any],
    application_data: Dict[str, Any],
) -> Dict[str, Any]:
    ownership_map = _ownership_profile()
    annotated: Dict[str, Any] = {}
    for key, value in services.items():
        if "units" in value:
            annotated_units: Dict[str, Any] = {}
            for unit_name, unit_state in value["units"].items():
                annotated_units[unit_name] = {
                    **unit_state,
                    "status": _derive_service_status(unit_state),
                }
            annotated[key] = {**value, "units": annotated_units}
            continue
        pressure = _derive_pressure(key, value, system_data, disk_data, application_data)
        status = _derive_service_status(value)
        if pressure == "critical":
            status = "critical"
        elif pressure == "concerning" and status == "healthy":
            status = "degraded"
        annotated[key] = {
            **value,
            "ownership": ownership_map.get(key),
            "pressure": pressure,
            "status": status,
        }
    return annotated


def _evaluate_backups(services: Dict[str, Any]) -> Dict[str, Any]:
    backups = services.get("backups", {})
    units = backups.get("units", {}) if isinstance(backups, dict) else {}
    issues: List[str] = []
    status = "healthy"

    for unit_name, unit_state in units.items():
        active_state = unit_state.get("active_state")
        if unit_name.endswith(".timer"):
            if active_state != "active":
                status = "critical"
                issues.append(f"{unit_name} is not active")
                continue
            age = unit_state.get("last_trigger_age_seconds")
            if age is None:
                if status != "critical":
                    status = "degraded"
                issues.append(f"{unit_name} has no recent trigger timestamp")
            elif age >= BACKUP_CRIT_AGE_SECONDS:
                status = "critical"
                issues.append(f"{unit_name} last triggered {int(age)}s ago")
            elif age >= BACKUP_WARN_AGE_SECONDS and status != "critical":
                status = "degraded"
                issues.append(f"{unit_name} last triggered {int(age)}s ago")
        else:
            # For oneshot services triggered by timers, "inactive" after success is normal
            result = unit_state.get("result")
            if active_state == "failed" or result == "failed":
                if status != "critical":
                    status = "degraded"
                issues.append(f"{unit_name} failed")
            elif active_state == "inactive" and result not in ("success", None):
                # Only flag inactive if result indicates a problem
                if status != "critical":
                    status = "degraded"
                issues.append(f"{unit_name} is {active_state} (result: {result})")

    return {
        "status": status,
        "issues": issues,
    }


def build_health_snapshot(
    per_check_timeout: float = DEFAULT_PER_CHECK_TIMEOUT,
    global_budget: float = DEFAULT_GLOBAL_BUDGET,
    process_limit: int = 10,
) -> Dict[str, Any]:
    start = time.monotonic()
    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
    }

    def _remaining_budget() -> float:
        return global_budget - (time.monotonic() - start)

    def _run_section(fn, *args, **kwargs):
        if _remaining_budget() <= 0:
            return _section_envelope({}, ["budget_exceeded"], 0)
        section_start = time.monotonic()
        data, errors = fn(*args, **kwargs)
        latency_ms = int((time.monotonic() - section_start) * 1000)
        return _section_envelope(data, errors, latency_ms)

    system_section = _run_section(_collect_system)
    result["system"] = system_section
    uptime_seconds = system_section["data"].get("uptime_seconds")
    result["processes"] = _run_section(_collect_processes, process_limit)
    disk_section = _run_section(_collect_disk)
    result["disk"] = disk_section
    result["network"] = _run_section(_collect_network)
    services_section = _run_section(_collect_services, uptime_seconds)
    application_section = _application_from_snapshot()
    services_section["data"] = _annotate_services(
        services_section["data"],
        system_section["data"],
        disk_section["data"],
        application_section["data"],
    )
    backups_summary = _evaluate_backups(services_section["data"])
    services_section["data"].setdefault("backups", {})
    services_section["data"]["backups"]["summary"] = backups_summary
    result["services"] = services_section
    result["application"] = application_section
    result["postgres_detail"] = _postgres_detail_from_snapshot()
    result["application_surfaces"] = _application_surfaces_section()

    return result
