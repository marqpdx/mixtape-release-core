# accounts/api/jwt_views.py

from django.conf import settings
from rest_framework import status
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.views import TokenViewBase
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
import datetime as dt

import logging

from . import serializers

logger = logging.getLogger(__name__)

# Centralize cookie names/flags
JWT_COOKIE_NAME   = getattr(settings, "JWT_COOKIE_NAME", "refresh_token")
JWT_COOKIE_DOMAIN = getattr(settings, "SESSION_COOKIE_DOMAIN", None)  # prod: ".crossroads.place"
JWT_COOKIE_PATH   = "/"
JWT_COOKIE_SAMESITE = getattr(settings, "JWT_COOKIE_SAMESITE", "Lax")  # prod: "None"
JWT_COOKIE_SECURE   = getattr(settings, "JWT_COOKIE_SECURE", False)    # prod: True

class TokenViewBaseWithCookie(TokenViewBase):

    serializer_class = serializers.TokenRefreshSerializer

    def post(self, request, *args, **kwargs):

        # logger.warning(f"""
        #     🔍 Token Request to {self.__class__.__name__}:
        #     Cookies received: {list(request.COOKIES.keys())}
        #     Has refresh_token: {'refresh_token' in request.COOKIES}
        #     Referer: {request.META.get('HTTP_REFERER', 'None')}
        #     Origin: {request.META.get('HTTP_ORIGIN', 'None')}
        #     """)

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request}  # Pass request context
        )

        try:
            serializer.is_valid(raise_exception=True)

            # Build response data
            response_data = {
                "success": True,
                **serializer.validated_data
            }

            resp = Response(response_data, status=status.HTTP_200_OK)

            # Set refresh token as httpOnly cookie
            expiration = dt.datetime.utcnow() + jwt_settings.REFRESH_TOKEN_LIFETIME

            resp.set_cookie(
                settings.JWT_COOKIE_NAME,
                serializer.validated_data["refresh"],
                expires=expiration,
                secure=settings.JWT_COOKIE_SECURE,
                httponly=True,
                samesite=settings.JWT_COOKIE_SAMESITE,
                path="/",
                domain=getattr(settings, "SESSION_COOKIE_DOMAIN", None),
            )

            logger.info(f"Token operation successful: {self.__class__.__name__}")
            return resp

        except (InvalidToken, AuthenticationFailed) as e:
            # Handle auth failures
            error_code = getattr(e, "code", "token_error")
            error_detail = getattr(e, "detail", str(e))

            logger.warning(
                f"Token operation failed: {self.__class__.__name__} - "
                f"Code: {error_code}, Detail: {error_detail}"
            )

            resp = Response(
                {
                    "success": False,
                    "detail": error_detail,
                    "code": error_code,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

            # Clear stale cookie
            resp.delete_cookie(
                settings.JWT_COOKIE_NAME,
                path="/",
                domain=getattr(settings, "SESSION_COOKIE_DOMAIN", None),
                samesite=getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax"),
            )

            return resp



class Login(TokenViewBaseWithCookie):
    serializer_class = serializers.EmailOrUsernameTokenSerializer


class RefreshToken(TokenViewBaseWithCookie):
    serializer_class = serializers.TokenRefreshSerializer




class Logout(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(JWT_COOKIE_NAME)

        # Try to blacklist if possible (only works if blacklist app is enabled)
        if refresh_token:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken
                token = RefreshToken(refresh_token)
                token.blacklist()
                logger.info("Refresh token blacklisted on logout")
            except Exception as e:
                logger.warning(f"Could not blacklist token on logout: {e}")

        resp = Response({"success": True, "detail": "Logged out successfully"}, status=status.HTTP_200_OK)

        # Primary deletion: current canonical flags
        resp.delete_cookie(
            key=JWT_COOKIE_NAME,
            domain=JWT_COOKIE_DOMAIN,
            path=JWT_COOKIE_PATH,
            samesite=JWT_COOKIE_SAMESITE,  # must match what was set
        )

        # Safety deletions for legacy/host-only cookies (no domain or api-only domain)
        for legacy_domain in (None, "api.crossroads.place"):
            resp.delete_cookie(
                key=JWT_COOKIE_NAME,
                domain=legacy_domain,
                path="/",
                samesite=JWT_COOKIE_SAMESITE,
            )

        logger.info("User logged out (cookies cleared)")
        return resp
