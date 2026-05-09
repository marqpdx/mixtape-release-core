from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from ops.models import OpsSnapshot
from ops.services.snapshot import build_health_snapshot


class OpsSnapshotTests(TestCase):
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    @patch("ops.services.snapshot._collect_application")
    def test_build_health_snapshot_uses_latest_postgres_snapshot(
        self,
        mock_application,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
    ):
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])
        mock_application.return_value = ({"postgres_active_connections": 6}, [])

        collected_at = timezone.now()
        expires_at = collected_at + timedelta(seconds=120)
        OpsSnapshot.objects.create(
            server_name="crossroads",
            subsystem="postgres",
            status="healthy",
            collected_at=collected_at,
            expires_at=expires_at,
            collector_version="1.0",
            data={
                "connection_breakdown": {"active": 6, "idle": 2, "idle_in_transaction": 0, "waiting": 0},
                "db_size_bytes": 123456,
                "long_running_queries": [],
                "top_tables": [],
                "cache_hit_ratio": 0.97,
                "dead_tuple_tables": [],
                "replication": [],
            },
            errors=[],
            latency_ms=42,
            source=OpsSnapshot.SOURCE_SCHEDULED,
        )

        snapshot = build_health_snapshot()

        self.assertIn("postgres_detail", snapshot)
        self.assertEqual(snapshot["postgres_detail"]["status"], "healthy")
        self.assertEqual(snapshot["postgres_detail"]["data"]["connection_breakdown"]["active"], 6)
        self.assertEqual(snapshot["postgres_detail"]["data"]["db_size_bytes"], 123456)

    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    @patch("ops.services.snapshot._collect_application")
    def test_build_health_snapshot_marks_expired_postgres_snapshot_stale(
        self,
        mock_application,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
    ):
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])
        mock_application.return_value = ({"postgres_active_connections": None}, [])

        collected_at = timezone.now() - timedelta(minutes=10)
        expires_at = timezone.now() - timedelta(minutes=8)
        OpsSnapshot.objects.create(
            server_name="crossroads",
            subsystem="postgres",
            status="healthy",
            collected_at=collected_at,
            expires_at=expires_at,
            collector_version="1.0",
            data={"connection_breakdown": {"active": 3}},
            errors=[],
            latency_ms=25,
            source=OpsSnapshot.SOURCE_SCHEDULED,
        )

        snapshot = build_health_snapshot()

        self.assertEqual(snapshot["postgres_detail"]["status"], "stale")
        self.assertIn("snapshot_stale", snapshot["postgres_detail"]["errors"])
