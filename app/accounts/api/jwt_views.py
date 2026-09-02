# accounts/api/jwt_views.py

import datetime as dt
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.views import TokenViewBase

from . import serializers
from .throttles import LoginThrottle, LogoutThrottle, TokenRefreshThrottle


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

        logger.warning(
            "🔍 Token Request to %s: cookies=%s has_refresh=%s origin=%s referer=%s",
            self.__class__.__name__,
            list(request.COOKIES.keys()),
            settings.JWT_COOKIE_NAME in request.COOKIES,
            request.META.get('HTTP_ORIGIN', 'None'),
            request.META.get('HTTP_REFERER', 'None'),
        )

        serializer = self.get_serializer(
            data=request.data,
            context={"request": request}  # Pass request context
        )

        try:
            serializer.is_valid(raise_exception=True)

            # Build response data — exclude refresh token from body;
            # it is delivered exclusively via the httpOnly cookie below.
            response_data = {
                "success": True,
                **{k: v for k, v in serializer.validated_data.items()
                   if k not in ("refresh", "refresh_expires")},
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
            # Handle auth failures — DRF stores code in e.detail.code, not e.code
            detail = getattr(e, "detail", None)
            error_code = (
                str(getattr(detail, "code", None))
                if detail is not None
                else getattr(e, "code", "token_error")
            ) or "token_error"
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
    throttle_classes = [LoginThrottle]


class RefreshToken(TokenViewBaseWithCookie):
    serializer_class = serializers.TokenRefreshSerializer
    throttle_classes = [TokenRefreshThrottle]


class Logout(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [LogoutThrottle]

    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(JWT_COOKIE_NAME)

        # Mode 3 (impersonation drift): if the caller was impersonating someone, this
        # denylists the impersonated user's JWT but leaves session impersonation keys
        # active. The session expires naturally. The superuser must re-authenticate to
        # reach /api/auth/assume/exit cleanly. No security escalation; operational confusion only.
        if refresh_token:
            try:
                from rest_framework_simplejwt.tokens import RefreshToken
                token = RefreshToken(refresh_token)
                token.blacklist()
                logger.info("Refresh token blacklisted on logout")
            except Exception as e:
                logger.warning("Could not blacklist refresh token on logout: %s", e)

        # Denylist the access token JTI so it cannot be used after logout
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            raw_access = auth_header.split(" ", 1)[1]
            try:
                from rest_framework_simplejwt.tokens import UntypedToken
                from .authentication import add_jti_to_denylist
                decoded = UntypedToken(raw_access)
                jti = decoded.get("jti")
                if jti:
                    ttl = int(jwt_settings.ACCESS_TOKEN_LIFETIME.total_seconds())
                    add_jti_to_denylist(jti, ttl)
            except Exception as e:
                logger.warning("Could not denylist access token JTI on logout: %s", e)

        resp = Response({"success": True, "detail": "Logged out successfully"}, status=status.HTTP_200_OK)

        # Delete refresh token cookie
        # Note: Must NOT specify domain parameter to delete host-only cookies (dev)
        # Production with SESSION_COOKIE_DOMAIN set will use that domain
        resp.delete_cookie(
            key=JWT_COOKIE_NAME,
            path=JWT_COOKIE_PATH,
            samesite=JWT_COOKIE_SAMESITE,
            domain=JWT_COOKIE_DOMAIN,  # Will be None in dev (host-only), set in production
        )

        logger.info("User logged out successfully")
        return resp
