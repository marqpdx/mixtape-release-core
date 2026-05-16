from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from ops.models import OpsSnapshot
from ops.services.snapshot import _application_surfaces_section, build_health_snapshot


class OpsSnapshotTests(TestCase):
    @patch("ops.services.snapshot._backup_detail_section")
    @patch("ops.services.snapshot._livewire_detail_section")
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
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "healthy",
            "data": {"monitors": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
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

    @patch("ops.services.snapshot._livewire_detail_section")
    @patch("ops.services.snapshot._backup_detail_section")
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
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "healthy",
            "data": {"monitors": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
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

    @patch("ops.services.snapshot._livewire_detail_section")
    @patch("ops.services.snapshot._backup_detail_section")
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
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "healthy",
            "data": {"monitors": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
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

    @patch("ops.services.snapshot._livewire_detail_section")
    @patch("ops.services.snapshot._backup_detail_section")
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
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "healthy",
            "data": {"monitors": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
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

    @patch("ops.services.snapshot._backup_detail_section")
    @patch("ops.services.snapshot._livewire_detail_section")
    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_includes_livewire_detail(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "healthy",
            "data": {"monitors": {}},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {
                "label": "Livewire",
                "provider": "socketio",
                "probe": {"url": "https://chat.crossroads.place/socket.io/?EIO=4&transport=polling"},
            },
            "errors": [],
            "latency_ms": 18,
            "collected_at": "2026-05-14T20:00:00Z",
            "expires_at": None,
            "source": "live",
        }
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

        snapshot = build_health_snapshot()

        self.assertIn("livewire_detail", snapshot)
        self.assertEqual(snapshot["livewire_detail"]["status"], "healthy")
        self.assertEqual(snapshot["livewire_detail"]["data"]["label"], "Livewire")

    @patch("ops.services.snapshot._backup_detail_section")
    @patch("ops.services.snapshot._livewire_detail_section")
    @patch("ops.services.snapshot._application_surfaces_section")
    @patch("ops.services.snapshot._collect_services")
    @patch("ops.services.snapshot._collect_network")
    @patch("ops.services.snapshot._collect_disk")
    @patch("ops.services.snapshot._collect_processes")
    @patch("ops.services.snapshot._collect_system")
    def test_build_health_snapshot_includes_backups_detail(
        self,
        mock_system,
        mock_processes,
        mock_disk,
        mock_network,
        mock_services,
        mock_application_surfaces,
        mock_livewire_detail,
        mock_backup_detail,
    ):
        mock_backup_detail.return_value = {
            "status": "degraded",
            "data": {"monitors": {"postgres": {"label": "Postgres Backups"}}},
            "errors": [],
            "latency_ms": 7,
            "collected_at": "2026-05-15T18:00:00Z",
            "expires_at": None,
            "source": "live",
        }
        mock_livewire_detail.return_value = {
            "status": "healthy",
            "data": {},
            "errors": [],
            "latency_ms": 0,
            "collected_at": None,
            "expires_at": None,
            "source": "live",
        }
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

        snapshot = build_health_snapshot()

        self.assertIn("backups_detail", snapshot)
        self.assertEqual(snapshot["backups_detail"]["status"], "degraded")
        self.assertIn("postgres", snapshot["backups_detail"]["data"]["monitors"])

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

    @override_settings(
        OPS_LIVEWIRE_MONITOR={
            "label": "Livewire",
            "provider": "local-socketio",
            "environment": "local",
            "endpoint": "http://127.0.0.1:5001",
            "probe_path": "/socket.io/?EIO=4&transport=polling",
        }
    )
    @patch("ops.services.snapshot._probe_http")
    @patch("ops.services.snapshot._probe_port")
    def test_livewire_detail_section_uses_settings_config(
        self,
        mock_probe_port,
        mock_probe_http,
    ):
        from ops.services.snapshot import _livewire_detail_section

        mock_probe_port.return_value = True
        mock_probe_http.return_value = (200, 35, None)

        section = _livewire_detail_section()

        self.assertEqual(section["status"], "healthy")
        self.assertEqual(section["source"], "live")
        self.assertEqual(section["data"]["provider"], "local-socketio")
        self.assertEqual(
            section["data"]["probe"]["url"],
            "http://127.0.0.1:5001/socket.io/?EIO=4&transport=polling",
        )
        mock_probe_port.assert_called_once_with("127.0.0.1", 5001)
        mock_probe_http.assert_called_once_with(
            "http://127.0.0.1:5001/socket.io/?EIO=4&transport=polling"
        )

    @override_settings(
        OPS_BACKUP_MONITORS={
            "postgres": {
                "label": "Postgres Backups",
                "timer_unit": "pg-backup.timer",
                "service_unit": "pg-backup.service",
                "upload_unit": "pg-backup-upload.service",
                "stamp_file": "/var/lib/backup-stamps/pg-backup.last_success",
                "interval_seconds": 72 * 3600,
                "off_host_required": True,
            }
        }
    )
    @patch("ops.services.snapshot._read_file", return_value=("1715800000\n", None))
    def test_backup_detail_section_reads_success_stamp(self, mock_read_file):
        from ops.services.snapshot import _backup_detail_section

        services = {
            "backups": {
                "units": {
                    "pg-backup.timer": {"active_state": "active"},
                    "pg-backup.service": {"active_state": "inactive", "result": "success"},
                    "pg-backup-upload.service": {"active_state": "inactive", "result": "success"},
                }
            }
        }

        section = _backup_detail_section(services)

        self.assertIn("postgres", section["data"]["monitors"])
        monitor = section["data"]["monitors"]["postgres"]
        self.assertEqual(monitor["label"], "Postgres Backups")
        self.assertEqual(monitor["off_host_status"], "healthy")
        self.assertEqual(monitor["stamp_file"], "/var/lib/backup-stamps/pg-backup.last_success")
        self.assertIsNotNone(monitor["last_success_at"])
