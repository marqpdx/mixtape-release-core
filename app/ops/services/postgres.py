from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any, Dict, List

from django.db import connection
from django.utils import timezone

from ops.models import OpsSnapshot

POSTGRES_COLLECTOR_VERSION = "1.0"
POSTGRES_SNAPSHOT_TTL_SECONDS = 120
POSTGRES_SERVER_NAME = "crossroads"
POSTGRES_SUBSYSTEM = "postgres"


@dataclass
class PostgresCollectionResult:
    status: str
    data: Dict[str, Any]
    errors: List[str]
    latency_ms: int
    collected_at: Any
    expires_at: Any


def collect_postgres_detail() -> PostgresCollectionResult:
    start = monotonic()
    errors: List[str] = []
    data: Dict[str, Any] = {
        "connection_breakdown": {
            "active": 0,
            "idle": 0,
            "idle_in_transaction": 0,
            "waiting": 0,
        },
        "long_running_queries": [],
        "db_size_bytes": None,
        "top_tables": [],
        "cache_hit_ratio": None,
        "dead_tuple_tables": [],
        "replication": [],
    }

    try:
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    SELECT state, COUNT(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                    GROUP BY state;
                    """
                )
                state_counts = {(state or "unknown"): count for state, count in cursor.fetchall()}
                data["connection_breakdown"].update(
                    {
                        "active": int(state_counts.get("active", 0)),
                        "idle": int(state_counts.get("idle", 0)),
                        "idle_in_transaction": int(state_counts.get("idle in transaction", 0)),
                    }
                )
            except Exception:
                errors.append("postgres_connection_breakdown_error")

            try:
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND wait_event_type IS NOT NULL
                      AND state != 'idle';
                    """
                )
                waiting_count = cursor.fetchone()[0]
                data["connection_breakdown"]["waiting"] = int(waiting_count or 0)
            except Exception:
                errors.append("postgres_waiting_count_error")

            try:
                cursor.execute(
                    """
                    SELECT
                      pid,
                      EXTRACT(EPOCH FROM (now() - pg_stat_activity.query_start)) AS duration_seconds,
                      query,
                      state
                    FROM pg_stat_activity
                    WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
                      AND state != 'idle'
                    ORDER BY duration_seconds DESC
                    LIMIT 5;
                    """
                )
                data["long_running_queries"] = [
                    {
                        "pid": int(pid),
                        "duration_seconds": float(duration_seconds or 0),
                        "query": (query or "")[:200],
                        "state": state or "unknown",
                    }
                    for pid, duration_seconds, query, state in cursor.fetchall()
                ]
            except Exception:
                errors.append("postgres_long_running_queries_error")

            try:
                cursor.execute("SELECT pg_database_size(current_database()) AS size_bytes;")
                row = cursor.fetchone()
                data["db_size_bytes"] = int(row[0]) if row and row[0] is not None else None
            except Exception:
                errors.append("postgres_database_size_error")

            try:
                cursor.execute(
                    """
                    SELECT
                      schemaname || '.' || tablename AS table_name,
                      pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)) AS total_bytes,
                      pg_relation_size(quote_ident(schemaname) || '.' || quote_ident(tablename)) AS table_bytes
                    FROM pg_tables
                    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY total_bytes DESC
                    LIMIT 10;
                    """
                )
                data["top_tables"] = [
                    {
                        "table_name": table_name,
                        "total_bytes": int(total_bytes or 0),
                        "table_bytes": int(table_bytes or 0),
                    }
                    for table_name, total_bytes, table_bytes in cursor.fetchall()
                ]
            except Exception:
                errors.append("postgres_top_tables_error")

            try:
                cursor.execute(
                    """
                    SELECT
                      sum(heap_blks_hit) / NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0)::float AS hit_ratio
                    FROM pg_statio_user_tables;
                    """
                )
                row = cursor.fetchone()
                data["cache_hit_ratio"] = float(row[0]) if row and row[0] is not None else None
            except Exception:
                errors.append("postgres_cache_hit_ratio_error")

            try:
                cursor.execute(
                    """
                    SELECT
                      schemaname || '.' || relname AS table_name,
                      n_dead_tup,
                      n_live_tup
                    FROM pg_stat_user_tables
                    ORDER BY n_dead_tup DESC
                    LIMIT 5;
                    """
                )
                data["dead_tuple_tables"] = [
                    {
                        "table_name": table_name,
                        "dead_tuples": int(dead_tuples or 0),
                        "live_tuples": int(live_tuples or 0),
                    }
                    for table_name, dead_tuples, live_tuples in cursor.fetchall()
                ]
            except Exception:
                errors.append("postgres_dead_tuple_tables_error")

            try:
                cursor.execute(
                    """
                    SELECT
                      client_addr::text,
                      COALESCE(
                        EXTRACT(EPOCH FROM replay_lag),
                        EXTRACT(EPOCH FROM flush_lag),
                        EXTRACT(EPOCH FROM write_lag),
                        0
                      )::int AS lag_seconds
                    FROM pg_stat_replication
                    ORDER BY lag_seconds DESC
                    LIMIT 3;
                    """
                )
                data["replication"] = [
                    {
                        "client_addr": client_addr or "unknown",
                        "lag_seconds": int(lag_seconds or 0),
                    }
                    for client_addr, lag_seconds in cursor.fetchall()
                ]
            except Exception:
                errors.append("postgres_replication_error")
    except Exception:
        errors.append("postgres_connection_error")

    collected_at = timezone.now()
    expires_at = collected_at + timedelta(seconds=POSTGRES_SNAPSHOT_TTL_SECONDS)
    latency_ms = int((monotonic() - start) * 1000)
    status = "healthy" if not errors else "degraded"

    return PostgresCollectionResult(
        status=status,
        data=data,
        errors=errors,
        latency_ms=latency_ms,
        collected_at=collected_at,
        expires_at=expires_at,
    )


def persist_postgres_snapshot(source: str = OpsSnapshot.SOURCE_SCHEDULED) -> OpsSnapshot:
    result = collect_postgres_detail()
    snapshot = OpsSnapshot.objects.create(
        server_name=POSTGRES_SERVER_NAME,
        subsystem=POSTGRES_SUBSYSTEM,
        status=result.status,
        collected_at=result.collected_at,
        expires_at=result.expires_at,
        collector_version=POSTGRES_COLLECTOR_VERSION,
        data=result.data,
        errors=result.errors,
        latency_ms=result.latency_ms,
        source=source,
    )
    return snapshot


def latest_postgres_snapshot() -> OpsSnapshot | None:
    return (
        OpsSnapshot.objects.filter(
            server_name=POSTGRES_SERVER_NAME,
            subsystem=POSTGRES_SUBSYSTEM,
        )
        .order_by("-collected_at", "-updated_at")
        .first()
    )
