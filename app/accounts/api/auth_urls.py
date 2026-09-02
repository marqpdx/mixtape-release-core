# ============================================================================
# accounts/api/auth_urls.py - CONSOLIDATED AUTH
# ============================================================================

from django.urls import path

from groups.api.views import accept_invite, invite_info

from . import jwt_views, views, password_reset_views, email_verify_views


urlpatterns = [
    # Core auth
    path("token", jwt_views.Login.as_view(), name="token-login"),
    path("token/refresh", jwt_views.RefreshToken.as_view(), name="token-refresh"),
    path("logout", jwt_views.Logout.as_view(), name="logout"),

    # User identity - THIS IS THE KEY ENDPOINT
    path("me", views.CurrentUserIdentity.as_view(), name="current-user-identity"),
    path("assume", views.AssumeUserView.as_view(), name="assume-user"),
    path("assume/exit", views.ExitAssumeUserView.as_view(), name="assume-user-exit"),
    # Returns: {
    #   id, username, email, is_superuser, is_staff,
    #   roles: ["member", "steward"],
    #   profile: { ... },
    #   groups: [ ... ],
    #   permissions: { granted: [...], effective: [...], groups: {...} }
    # }

    # Permissions
    path("permissions/refresh", views.refresh_permissions, name="refresh-permissions"),

    # Registration
    path("signup", views.user_create_view, name="user-register"),

    # Password reset
    path("password-reset", password_reset_views.PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm", password_reset_views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # Email verification
    path("verify-email", email_verify_views.EmailVerifyView.as_view(), name="verify-email"),
    path("verify-email/resend", email_verify_views.ResendVerificationEmailView.as_view(), name="verify-email-resend"),

    # Utilities
    path("csrf", views.csrf, name="csrf-token"),
    path("check-username/<str:username>", views.check_username, name="check-username"),
    path("accept-invite", accept_invite, name="accept-invite"),
    path("invite-info/<str:shortcode>", invite_info, name="invite-info"),
]
