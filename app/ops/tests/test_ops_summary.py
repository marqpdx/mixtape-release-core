"""
Tests for Ops summary endpoint.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient


class OpsSummaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.superuser = User.objects.create_user(
            username="ops_admin",
            password="password",
            is_superuser=True,
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="regular_user",
            password="password",
        )

    def test_summary_requires_superuser(self):
        response = self.client.get("/api/ops/summary")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/ops/summary")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ops.api.views.build_health_snapshot")
    def test_summary_highlights_backup_and_disk(self, mock_snapshot):
        mock_snapshot.return_value = {
            "generated_at": "2026-01-17T18:00:00Z",
            "system": {"status": "ok", "data": {"swap_bytes": {"used": 0, "total": 0}}},
            "disk": {"status": "ok", "data": {"root": {"free_percent": 4.0}}},
            "network": {"status": "ok", "data": {}},
            "application": {
                "status": "ok",
                "data": {"celery_queue_depth": 0, "rabbitmq_connection_count": 1},
            },
            "services": {
                "status": "ok",
                "data": {
                    "backups": {"summary": {"status": "critical", "issues": ["pg-backup.timer is not active"]}}
                },
            },
        }

        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/api/ops/summary")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("highlights", response.data)
        self.assertIn("Backups need attention.", response.data["highlights"])
        self.assertIn("Low disk space on the server.", response.data["highlights"])

    @patch("ops.api.views.build_health_snapshot")
    def test_summary_structure(self, mock_snapshot):
        mock_snapshot.return_value = {
            "generated_at": "2026-01-17T18:00:00Z",
            "system": {"status": "ok", "data": {"swap_bytes": {"used": 0, "total": 0}}},
            "disk": {"status": "ok", "data": {"root": {"free_percent": 40.0}}},
            "network": {"status": "ok", "data": {}},
            "application": {"status": "ok", "data": {"celery_queue_depth": 0}},
            "services": {"status": "ok", "data": {"backups": {"summary": {"status": "healthy"}}}},
        }

        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/api/ops/summary")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("overall_status", response.data)
        self.assertIn("headline", response.data)
        self.assertIn("tiles", response.data)

    def test_tiles_requires_superuser(self):
        response = self.client.get("/api/ops/tiles")
        self.assertIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        self.client.force_authenticate(user=self.user)
        response = self.client.get("/api/ops/tiles")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ops.api.views.build_health_snapshot")
    def test_tiles_structure(self, mock_snapshot):
        mock_snapshot.return_value = {
            "generated_at": "2026-01-17T18:00:00Z",
            "system": {"status": "ok", "data": {"swap_bytes": {"used": 0, "total": 0}}},
            "disk": {"status": "ok", "data": {"root": {"free_percent": 40.0}}},
            "network": {"status": "ok", "data": {}},
            "application": {"status": "ok", "data": {"celery_queue_depth": 0}},
            "services": {"status": "ok", "data": {"backups": {"summary": {"status": "healthy"}}}},
        }

        self.client.force_authenticate(user=self.superuser)
        response = self.client.get("/api/ops/tiles")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("timestamp", response.data)
        self.assertIn("tiles", response.data)
