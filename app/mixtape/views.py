# mixtape/views.py
"""
Core application views including health check and CSRF endpoints
"""

from django.db import connection
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
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


@require_http_methods(["GET"])
@ensure_csrf_cookie
def csrf_token_view(request):
    """
    CSRF token endpoint for frontend authentication.

    Returns:
        - 200 OK with CSRF token in JSON response
        - Sets csrftoken cookie via @ensure_csrf_cookie decorator

    Used by:
        - Frontend auth initialization (lib/auth/api.ts)
        - Called once on app mount to get CSRF token
    """
    return JsonResponse({
        "csrfToken": get_token(request),
    }, status=200)

