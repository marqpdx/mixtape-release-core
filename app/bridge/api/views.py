from datetime import timedelta

from livekit.api import AccessToken, VideoGrants
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from almanac.models import OccurrenceAttendee
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

    # Phase B: validate RSVP / attendance before issuing a room token.
    # Superusers may join any session for moderation purposes.
    if not request.user.is_superuser:
        if session.occurrence is None:
            return Response(
                {"detail": "This session is not open for public access."},
                status=status.HTTP_403_FORBIDDEN,
            )
        is_attendee = OccurrenceAttendee.objects.filter(
            occurrence=session.occurrence,
            user=request.user,
            status__in=["going", "maybe", "attended"],
        ).exists()
        if not is_attendee:
            return Response(
                {"detail": "You are not registered for this session."},
                status=status.HTTP_403_FORBIDDEN,
            )

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
