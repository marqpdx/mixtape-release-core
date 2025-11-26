# activity/api/permissions.py

from rest_framework.permissions import IsAuthenticated
import logging

logger = logging.getLogger(__name__)


class LoggingIsAuthenticated(IsAuthenticated):
    """
    Custom permission that logs auth failures for debugging.
    Remove or disable logging in production.
    """

    def has_permission(self, request, view):
        is_authed = request.user.is_authenticated

        # Only log if NOT authenticated (to debug 401s)
        if not is_authed:
            pass
            # logger.warning(f"""
            #     🔍 Authentication Failed for {request.path}:
            #     User: {request.user}
            #     Auth Header: {request.META.get('HTTP_AUTHORIZATION', 'None')[:50] if request.META.get('HTTP_AUTHORIZATION') else 'None'}
            #     Referer: {request.META.get('HTTP_REFERER', 'None')}
            #     Origin: {request.META.get('HTTP_ORIGIN', 'None')}
            #     User-Agent: {request.META.get('HTTP_USER_AGENT', 'None')[:80]}
            #     Cookies Present: {list(request.COOKIES.keys())}
            #     Has refresh_token cookie: {'refresh_token' in request.COOKIES}
            #     """)

        return super().has_permission(request, view)