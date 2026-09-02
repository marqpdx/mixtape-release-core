# accounts/api/password_reset_views.py

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from .throttles import PasswordResetThrottle

User = get_user_model()
logger = logging.getLogger(__name__)

FRONTEND_URL = getattr(settings, "FRONTEND_URL", "http://localhost:3000")


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        if not email:
            return Response(
                {"detail": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email__iexact=email, is_active=True)
        except User.DoesNotExist:
            user = None

        if user is not None:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url = f"{FRONTEND_URL}/update-password?uid={uid}&token={token}"

            form = PasswordResetForm({"email": email})
            if form.is_valid():
                # Background thread so both code paths return in the same wall-clock
                # time — prevents timing oracle on account existence.
                threading.Thread(
                    target=form.save,
                    kwargs=dict(
                        request=request,
                        use_https=request.is_secure(),
                        token_generator=default_token_generator,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        email_template_name="email/password_reset.txt",
                        html_email_template_name="email/password_reset.html",
                        extra_email_context={"reset_url": reset_url, "site_name": "Crossroads"},
                    ),
                    daemon=True,
                ).start()
                logger.info("Password reset email dispatched (background)")
            else:
                logger.warning("PasswordResetForm invalid — check email format validation")
        else:
            logger.info("Password reset requested for unregistered address")

        return Response({"detail": "If an account exists, a reset link has been sent."})


class PasswordResetConfirmView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetThrottle]

    def post(self, request):
        uid_b64 = request.data.get("uid", "")
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")

        if not all([uid_b64, token, new_password]):
            return Response(
                {"detail": "uid, token, and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uid = force_str(urlsafe_base64_decode(uid_b64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Reset link has expired or is invalid."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        form = SetPasswordForm(user, {"new_password1": new_password, "new_password2": new_password})
        if not form.is_valid():
            errors = form.errors.get("new_password2", form.errors)
            return Response({"detail": str(errors)}, status=status.HTTP_400_BAD_REQUEST)

        form.save()

        # Invalidate all outstanding refresh tokens so a captured token
        # cannot be used to mint new access tokens after a password reset.
        try:
            from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
            from rest_framework_simplejwt.utils import aware_utcnow
            outstanding = OutstandingToken.objects.filter(user=user, expires_at__gt=aware_utcnow())
            for token in outstanding:
                BlacklistedToken.objects.get_or_create(token=token)
            logger.info("Blacklisted %d outstanding refresh tokens after password reset", outstanding.count())
        except Exception as e:
            logger.warning("Could not blacklist tokens after password reset: %s", e)

        logger.info("Password reset completed")

        return Response({"detail": "Password has been reset successfully."})
