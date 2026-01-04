"""
Tests for Health Check Endpoint

Tests the /api/stackroom/health endpoint:
- Database connectivity check
- Qdrant connectivity check
- Overall health status
"""

from unittest.mock import patch, Mock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status


class HealthCheckTests(TestCase):
    """Test health check endpoint"""

    def setUp(self):
        """Set up test client"""
        self.client = APIClient()

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_health_check_all_healthy(self, mock_get_qdrant):
        """Test health check when all systems are healthy"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = ["collection1", "collection2"]
        mock_get_qdrant.return_value = mock_qdrant

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")

        # Verify database check
        self.assertIn("database", response.data["checks"])
        self.assertEqual(response.data["checks"]["database"]["status"], "healthy")

        # Verify Qdrant check
        self.assertIn("qdrant", response.data["checks"])
        self.assertEqual(response.data["checks"]["qdrant"]["status"], "healthy")
        self.assertEqual(response.data["checks"]["qdrant"]["collection_count"], 2)

        # Verify timestamp
        self.assertIn("timestamp", response.data)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_health_check_qdrant_unhealthy(self, mock_get_qdrant):
        """Test health check when Qdrant is unavailable"""
        # Mock Qdrant client to raise exception
        mock_get_qdrant.side_effect = Exception("Connection refused")

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify degraded status
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "degraded")

        # Verify database still healthy
        self.assertEqual(response.data["checks"]["database"]["status"], "healthy")

        # Verify Qdrant unhealthy
        self.assertEqual(response.data["checks"]["qdrant"]["status"], "unhealthy")
        self.assertIn("Connection refused", response.data["checks"]["qdrant"]["message"])

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("django.db.connection.cursor")
    def test_health_check_database_unhealthy(self, mock_cursor, mock_get_qdrant):
        """Test health check when database is unavailable"""
        # Mock database error
        mock_cursor.side_effect = Exception("Database connection failed")

        # Mock Qdrant healthy
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify degraded status
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "degraded")

        # Verify database unhealthy
        self.assertEqual(response.data["checks"]["database"]["status"], "unhealthy")
        self.assertIn("Database connection failed", response.data["checks"]["database"]["message"])

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    @patch("django.db.connection.cursor")
    def test_health_check_all_unhealthy(self, mock_cursor, mock_get_qdrant):
        """Test health check when both systems are down"""
        # Mock database error
        mock_cursor.side_effect = Exception("Database down")

        # Mock Qdrant error
        mock_get_qdrant.side_effect = Exception("Qdrant down")

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify degraded status
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "degraded")

        # Verify both unhealthy
        self.assertEqual(response.data["checks"]["database"]["status"], "unhealthy")
        self.assertEqual(response.data["checks"]["qdrant"]["status"], "unhealthy")

    def test_health_check_no_authentication_required(self):
        """Test that health check endpoint does not require authentication"""
        # Call without authentication
        response = self.client.get("/api/stackroom/health")

        # Should not return 401/403
        self.assertNotIn(response.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_health_check_response_structure(self, mock_get_qdrant):
        """Test that response has correct structure"""
        # Mock Qdrant
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = []
        mock_get_qdrant.return_value = mock_qdrant

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify top-level keys
        self.assertIn("status", response.data)
        self.assertIn("timestamp", response.data)
        self.assertIn("checks", response.data)

        # Verify checks structure
        self.assertIn("database", response.data["checks"])
        self.assertIn("qdrant", response.data["checks"])

        # Verify each check has required fields
        for check_name in ["database", "qdrant"]:
            check = response.data["checks"][check_name]
            self.assertIn("status", check)
            self.assertIn("message", check)

    @patch("stackroom.services.qdrant_client.get_qdrant_client")
    def test_health_check_collection_count(self, mock_get_qdrant):
        """Test that collection count is included in healthy Qdrant check"""
        # Mock Qdrant with specific collection count
        mock_qdrant = Mock()
        mock_qdrant.list_collections.return_value = ["col1", "col2", "col3"]
        mock_get_qdrant.return_value = mock_qdrant

        # Call health endpoint
        response = self.client.get("/api/stackroom/health")

        # Verify collection count
        self.assertEqual(
            response.data["checks"]["qdrant"]["collection_count"],
            3
        )
