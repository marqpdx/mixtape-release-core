"""
A rotated refresh token is recorded as outstanding, so the password-reset
view's blacklist loop (accounts/api/password_reset_views.py) can end it.

Before the fix, TokenRefreshSerializer.validate rotated with set_jti() and
set_exp() but never called outstand(), so the rotated token had no
OutstandingToken row and survived a password reset.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import aware_utcnow

from accounts.api.serializers import TokenRefreshSerializer

User = get_user_model()


class RotatedRefreshTokenIsOutstandingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="rotation-user", email="rotation@example.com", password="testpass123"
        )

    def _refresh(self, token: str) -> dict:
        request = RequestFactory().post("/")
        request.COOKIES[settings.JWT_COOKIE_NAME] = token
        serializer = TokenRefreshSerializer(data={}, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def test_rotated_refresh_token_is_recorded(self):
        original = RefreshToken.for_user(self.user)
        data = self._refresh(str(original))

        rotated = RefreshToken(data["refresh"])
        self.assertNotEqual(rotated["jti"], original["jti"])
        self.assertTrue(OutstandingToken.objects.filter(jti=rotated["jti"], user=self.user).exists())

    def test_password_reset_loop_ends_the_rotated_token(self):
        data = self._refresh(str(RefreshToken.for_user(self.user)))

        # The same loop the password-reset view runs after form.save().
        for token in OutstandingToken.objects.filter(user=self.user, expires_at__gt=aware_utcnow()):
            BlacklistedToken.objects.get_or_create(token=token)

        with self.assertRaises(TokenError):
            RefreshToken(data["refresh"]).check_blacklist()
