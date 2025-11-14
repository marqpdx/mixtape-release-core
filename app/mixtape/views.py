# mixtape/views.py
"""
Core application views including health check endpoint
"""

from django.http import JsonResponse
from django.db import connection
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint for monitoring and deployment verification.

    Returns:
        - 200 OK if application is healthy (database connection works)
        - 500 Internal Server Error if there are issues

    Used by:
        - Playwright E2E tests (global-setup.ts)
        - GitHub Actions CI/CD (deployment verification)
        - Production health monitoring
        - Load balancer health checks
    """
    try:
        # Test database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        return JsonResponse({
            "status": "healthy",
            "database": "connected",
        }, status=200)

    except Exception as e:
        return JsonResponse({
            "status": "unhealthy",
            "error": str(e),
        }, status=500)

