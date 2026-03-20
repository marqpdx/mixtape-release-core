# users/api/views.py
"""
Push token registration endpoint.
POST /api/push/register/ — upsert a device push token for the authenticated user.
"""
import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import PushToken

logger = logging.getLogger(__name__)


class PushTokenRegisterView(APIView):
    """
    POST /api/push/register/
    Body: { "token": "<expo_push_token>", "platform": "ios|android|web", "environment": "production|sandbox|development" }

    Idempotent upsert: if the token already exists for any user, it is reassigned
    to the current user (handles reinstall / account switch). Platform and
    environment are always updated to the latest values.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token_str = (request.data.get("token") or "").strip()
        platform = request.data.get("platform", PushToken.Platform.IOS)
        environment = request.data.get("environment", PushToken.Environment.PRODUCTION)

        if not token_str:
            return Response({"error": "token is required"}, status=400)

        if platform not in PushToken.Platform.values:
            return Response({"error": f"platform must be one of {PushToken.Platform.values}"}, status=400)

        if environment not in PushToken.Environment.values:
            return Response({"error": f"environment must be one of {PushToken.Environment.values}"}, status=400)

        obj, created = PushToken.objects.update_or_create(
            token=token_str,
            defaults={
                "user": request.user,
                "platform": platform,
                "environment": environment,
                "is_active": True,
            },
        )

        action = "registered" if created else "updated"
        logger.info(
            "push_token_%s user=%s platform=%s env=%s token_prefix=%s",
            action, request.user.id, platform, environment, token_str[:12],
        )

        return Response({"status": action, "platform": platform, "environment": environment})
