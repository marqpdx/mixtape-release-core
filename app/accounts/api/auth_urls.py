# ============================================================================
# accounts/api/auth_urls.py - CONSOLIDATED AUTH
# ============================================================================

from django.urls import path
from . import jwt_views, views

urlpatterns = [
    # Core auth
    path('token', jwt_views.Login.as_view(), name='token-login'),
    path('token/refresh', jwt_views.RefreshToken.as_view(), name='token-refresh'),
    path('logout', jwt_views.Logout.as_view(), name='logout'),

    # User identity - THIS IS THE KEY ENDPOINT
    path('me', views.CurrentUserIdentity.as_view(), name='current-user-identity'),
    # Returns: {
    #   id, username, email, is_superuser, is_staff,
    #   roles: ["member", "steward"],
    #   profile: { ... },
    #   groups: [ ... ],
    #   permissions: { granted: [...], effective: [...], groups: {...} }
    # }

    # Permissions
    path('permissions/refresh', views.refresh_permissions, name='refresh-permissions'),

    # Registration
    path('signup', views.user_create_view, name='user-register'),

    # Utilities
    path('csrf', views.csrf, name='csrf-token'),
    path('check-username/<str:username>', views.check_username, name='check-username'),
]
