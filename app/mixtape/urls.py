# app/mixtape/urls.py

from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from accounts.api.views import UserViewSet

from . import views


router = routers.DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

# ============================================================================
# PHASE 1: MINIMAL URL CONFIGURATION
# ============================================================================
# Only authentication and member endpoints enabled
# Other endpoints will be added back in future phases
# ============================================================================

urlpatterns = [
    # Django admin
    path("admin/", admin.site.urls),

    # DRF browsable API login
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),

    # Health check (for monitoring, tests, and deployment)
    path("health/", views.health_check, name="health_check"),

    # CSRF token endpoint (for frontend auth initialization)
    path("api/csrf/", views.csrf_token_view, name="csrf_token"),

    # === PHASE 1 ENDPOINTS ===

    # Authentication
    path("api/auth/", include("accounts.api.auth_urls")),
    # Endpoints: /api/auth/token, /api/auth/token/refresh, /api/auth/logout, /api/auth/me

    # Members (User + Profile combined)
    path("api/members/", include("profiles.api.urls")),

    # Endpoints: /api/members/, /api/members/<slug>/

    # === END PHASE 1 ENDPOINTS ===

    # === PHASE 2 ENDPOINTS ===

    # Groups
    path("api/groups/", include("groups.api.urls")),

    path("api/almanac/", include("almanac.api.urls")),
    path("api/assets/", include("assets.api.urls")),
    path("api/chat/", include("chat.api.urls")),
    path("api/dispatch/", include("dispatch.api.urls")),
    path('api/gristmill/', include('gristmill.api.urls')),
    path("api/inkwell/", include("inkwell.api.urls")),
    path("api/lanternmail/", include("lanternmail.api.urls")),  # Global lanternmail endpoints
    path("api/livewire/", include("livewire.api.urls")),
    path("api/projects/", include("projects.api.urls")),
    path("api/stackroom/", include("stackroom.api.urls")),
    path('api/threadworks/', include('threadworks.api.urls')),
    path("api/writing/", include("writing.api.urls")),

    # DRF Router endpoints
    path("api/", include(router.urls)),
]

# ============================================================================
# DEFERRED ENDPOINTS (Add back in later phases):
# - path('api/groups', include('groups.api.urls'))
# - path('api/ai/', include('ai.api.urls'))

# - path('api/writing/', include('writing.api.urls'))
# - path('api/assets', include('assets.api.urls'))
# - path("api/identity/", include("identity.api.urls"))
# - And many others...
# ============================================================================
