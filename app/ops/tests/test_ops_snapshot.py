from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from ops.models import OpsSnapshot
from ops.services.snapshot import _application_surfaces_section, build_health_snapshot


class OpsSnapshotTests(TestCase):
    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_uses_latest_postgres_snapshot(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
    ):
        mock_application_surfaces.return_value = {
            "status": "healthy",
            "data": {"surfaces": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])

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
        OpsSnapshot.objects.create(
            server_name="crossroads",
            subsystem="application",
            status="healthy",
            collected_at=collected_at,
            expires_at=expires_at,
            collector_version="1.0",
            data={"celery_queue_depth": 0, "rabbitmq_connection_count": 1},
            errors=[],
            latency_ms=31,
            source=OpsSnapshot.SOURCE_SCHEDULED,
        )

        snapshot = build_health_snapshot()

        self.assertIn("postgres_detail", snapshot)
        self.assertEqual(snapshot["postgres_detail"]["status"], "healthy")
        self.assertEqual(snapshot["postgres_detail"]["data"]["connection_breakdown"]["active"], 6)
        self.assertEqual(snapshot["postgres_detail"]["data"]["db_size_bytes"], 123456)
        self.assertEqual(snapshot["application"]["status"], "healthy")
        self.assertEqual(snapshot["application"]["data"]["postgres_active_connections"], 6)

    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_marks_expired_postgres_snapshot_stale(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
    ):
        mock_application_surfaces.return_value = {
            "status": "healthy",
            "data": {"surfaces": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])

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

    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_uses_latest_application_snapshot(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
    ):
        mock_application_surfaces.return_value = {
            "status": "healthy",
            "data": {"surfaces": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])

        collected_at = timezone.now()
        expires_at = collected_at + timedelta(seconds=120)
        OpsSnapshot.objects.create(
            server_name="crossroads",
            subsystem="application",
            status="healthy",
            collected_at=collected_at,
            expires_at=expires_at,
            collector_version="1.0",
            data={"celery_queue_depth": 8, "rabbitmq_connection_count": 4, "rabbitmq_vhost": "/crossroads"},
            errors=[],
            latency_ms=18,
            source=OpsSnapshot.SOURCE_SCHEDULED,
        )

        snapshot = build_health_snapshot()

        self.assertEqual(snapshot["application"]["status"], "healthy")
        self.assertEqual(snapshot["application"]["data"]["celery_queue_depth"], 8)
        self.assertEqual(snapshot["application"]["data"]["rabbitmq_connection_count"], 4)

    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_includes_application_surfaces(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
    ):
        mock_application_surfaces.return_value = {
            "status": "healthy",
            "data": {
                "surfaces": {
                    "mixtape-web": {
                        "label": "Mixtape Web",
                        "status": "healthy",
                        "provider": "local-next",
                    }
                }
            },
            "errors": [],
            "latency_ms": 12,
            "collected_at": "2026-05-14T20:00:00Z",
            "expires_at": None,
            "source": "live",
        }
        mock_system.return_value = ({"uptime_seconds": 123.0, "swap_bytes": {"used": 0, "total": 0}}, [])
        mock_processes.return_value = ({"top_rss": [], "top_cpu": [], "limit": 10}, [])
        mock_disk.return_value = ({"root": {"free_percent": 40.0}}, [])
        mock_network.return_value = ({}, [])
        mock_services.return_value = ({"backups": {"units": {}}}, [])

        snapshot = build_health_snapshot()

        self.assertIn("application_surfaces", snapshot)
        self.assertEqual(snapshot["application_surfaces"]["status"], "healthy")
        self.assertIn("mixtape-web", snapshot["application_surfaces"]["data"]["surfaces"])

    @override_settings(
        OPS_APPLICATION_SURFACES={
            "django-api": {
                "label": "Django API",
                "surface_type": "api",
                "provider": "runserver",
                "environment": "local",
                "endpoint": "http://127.0.0.1:8010",
                "probe_paths": ["/health/"],
            }
        }
    )
    @patch("ops.services.snapshot._probe_http")
    @patch("ops.services.snapshot._probe_port")
    def test_application_surfaces_section_uses_settings_config(
        self,
        mock_probe_port,
        mock_probe_http,
    ):
        mock_probe_port.return_value = True
        mock_probe_http.return_value = (200, 42, None)

        section = _application_surfaces_section()

        self.assertEqual(section["status"], "healthy")
        self.assertEqual(section["source"], "live")
        self.assertEqual(section["data"]["surfaces"]["django-api"]["label"], "Django API")
        self.assertEqual(section["data"]["surfaces"]["django-api"]["provider"], "runserver")
        self.assertEqual(section["data"]["surfaces"]["django-api"]["endpoint"], "http://127.0.0.1:8010")
        self.assertEqual(
            section["data"]["surfaces"]["django-api"]["probes"][0]["url"],
            "http://127.0.0.1:8010/health/",
        )
        mock_probe_port.assert_called_once_with("127.0.0.1", 8010)
        mock_probe_http.assert_called_once_with("http://127.0.0.1:8010/health/")
