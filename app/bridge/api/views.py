from datetime import timedelta

from livekit.api import AccessToken, VideoGrants
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from bridge.models import BridgeSession


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def room_token(request):
    session_id = request.data.get("session_id")
    if not session_id:
        return Response({"detail": "session_id required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        session = BridgeSession.objects.select_related("occurrence").get(id=session_id)
    except BridgeSession.DoesNotExist:
        return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    # Phase A: any authenticated user may join.
    # Phase B+: validate EventOccurrence membership / RSVP.

    token = (
        AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(str(request.user.id))
        .with_name(request.user.get_username())
        .with_grants(VideoGrants(room_join=True, room=session.room_name))
        .with_ttl(timedelta(seconds=settings.LIVEKIT_ROOM_TOKEN_TTL_SECONDS))
        .to_jwt()
    )

    return Response({
        "token": token,
        "room_name": session.room_name,
        "livekit_url": settings.LIVEKIT_URL,
    })
