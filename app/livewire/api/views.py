# livewire/api/views.py

import time

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


User = get_user_model()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def livewire_token(request):
    now = int(time.time())
    claims = {
        "sub": str(request.user.id),
        "username": request.user.get_username(),
        "iat": now,
        "nbf": now,
        "exp": now + 60 * 30,  # 30 minutes; adjust as you like
        "iss": settings.LIVEWIRE_JWT_ISS,
        "aud": settings.LIVEWIRE_JWT_AUD,
    }
    token = jwt.encode(
        claims,
        settings.LIVEWIRE_JWT_SECRET,
        algorithm=getattr(settings, "LIVEWIRE_JWT_ALG", "HS256"),
    )
    return Response({"token": token, "exp": claims["exp"]})



def _verify_ws_token(token: str) -> dict:
    """Verify the WS token minted for Socket.IO handshake."""
    return jwt.decode(
        token,
        settings.LIVEWIRE_JWT_SECRET,
        algorithms=[getattr(settings, "LIVEWIRE_JWT_ALG", "HS256")],
        issuer=getattr(settings, "LIVEWIRE_JWT_ISS", "mixtape"),
        audience=getattr(settings, "LIVEWIRE_JWT_AUD", "livewire"),
        options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
    )


def _mint_service_token(
    user_id: str,
    scopes: list[str],
    conv: str | None = None,
) -> dict:
    """Mint a short-lived, scoped service token for Node->Django calls."""
    now = int(time.time())
    ttl = int(getattr(settings, "SERVICE_JWT_TTL_SECONDS", 600))
    claims = {
        "sub": user_id,
        "scopes": scopes,                 # e.g., ["chat:write"]
        "iat": now, "nbf": now, "exp": now + ttl,
        "iss": getattr(settings, "SERVICE_JWT_ISS", "mixtape"),
        "aud": getattr(settings, "SERVICE_JWT_AUD", "django-api"),
    }
    if conv:
        claims["conv"] = conv            # optional: bind token to a conversation
    token = jwt.encode(
        claims,
        settings.SERVICE_JWT_SECRET,
        algorithm=getattr(settings, "SERVICE_JWT_ALG", "HS256"),
    )
    return {"service_token": token, "exp": claims["exp"]}


@api_view(["POST"])
@permission_classes([AllowAny])  # we verify WS token ourselves here
def exchange_ws_for_service_token(request):
    """
    Body: { "ws_token": "<WS token from client>", "conv": "<optional conversation slug>" }
    Returns: { "service_token": "...", "exp": <unix> }
    """
    data = request.data or {}
    ws_token = data.get("ws_token")
    conv = data.get("conv")
    if not ws_token:
        return Response({"detail": "ws_token required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ws_claims = _verify_ws_token(ws_token)
        uid = ws_claims.get("sub")
        uname = ws_claims.get("username")

        user_obj = None
        if uid is not None:
            try:
                user_obj = User.objects.get(pk=uid)
            except User.DoesNotExist:
                user_obj = None

        if user_obj is None and uname:
            try:
                user_obj = User.objects.get(**{User.USERNAME_FIELD: uname})
            except User.DoesNotExist:
                user_obj = None

        if user_obj is None:
            return Response({"detail": "user not found for WS token"}, status=401)

        # TODO: Validate user has permission to access conversation `conv` before minting token
        result = _mint_service_token(user_id=str(user_obj.pk), scopes=["chat:write"], conv=conv)

        return Response(result, status=status.HTTP_200_OK)

    except jwt.PyJWTError as e:
        return Response({"detail": f"invalid ws token: {e}"}, status=status.HTTP_401_UNAUTHORIZED)
