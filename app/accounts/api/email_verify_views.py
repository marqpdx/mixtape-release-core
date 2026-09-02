# accounts/api/email_verify_views.py

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

User = get_user_model()

FRONTEND_URL = getattr(settings, "FRONTEND_URL", "https://www.crossroads.place")


def send_verification_email(user):
    """Dispatch the email verification link in a daemon thread."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_url = f"{FRONTEND_URL}/app/verify-email?uid={uid}&token={token}"

    subject = "Verify your Crossroads email"
    body = render_to_string(
        "email/email_verification.txt",
        {"user": user, "verify_url": verify_url, "site_name": "Crossroads"},
    )
    html_body = render_to_string(
        "email/email_verification.html",
        {"user": user, "verify_url": verify_url, "site_name": "Crossroads"},
    )

    def _send():
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_body,
                fail_silently=False,
            )
            logger.info("Verification email dispatched to %s", user.email)
        except Exception as exc:
            logger.error("Failed to send verification email to %s: %s", user.email, exc)

    threading.Thread(target=_send, daemon=True).start()


class EmailVerifyView(APIView):
    """
    POST /api/auth/verify-email

    Accepts a uid + token from the verification link and marks the account verified.
    Uses Django's default_token_generator (HMAC, expires per PASSWORD_RESET_TIMEOUT).

    Request body: { "uid": "...", "token": "..." }
    """

    permission_classes = [AllowAny]

    def post(self, request):
        uid_b64 = request.data.get("uid", "")
        token = request.data.get("token", "")

        if not uid_b64 or not token:
            return Response(
                {"detail": "uid and token are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uid = force_str(urlsafe_base64_decode(uid_b64))
            user = User.users.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            return Response(
                {"detail": "Invalid verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Verification link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.email_verified:
            return Response({"detail": "Email already verified."}, status=status.HTTP_200_OK)

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        logger.info("Email verified for user %s", user.pk)

        return Response({"detail": "Email verified successfully."}, status=status.HTTP_200_OK)


class ResendVerificationEmailView(APIView):
    """
    POST /api/auth/verify-email/resend

    Resends the verification email for the authenticated user.
    No-ops silently if already verified (don't leak verification state to unauthenticated callers).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.email_verified:
            send_verification_email(user)
        return Response(
            {"detail": "If your email is unverified, a new link has been sent."},
            status=status.HTTP_200_OK,
        )
