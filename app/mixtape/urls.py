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

    # OAuth2 Authorization Server (for desktop/mobile apps)
    path("oauth/", include("oauth2_provider.urls", namespace="oauth2_provider")),
    # Endpoints: /oauth/authorize, /oauth/token, /oauth/revoke_token, etc.

    # Members (User + Profile combined)
    path("api/members/", include("profiles.api.urls")),

    # Endpoints: /api/members/, /api/members/<slug>

    # === END PHASE 1 ENDPOINTS ===

    # Public API (anonymous + logged-in reader surface)
    path("api/public/", include("public_api.urls")),

    # === PHASE 2 ENDPOINTS ===

    # Groups
    path("api/groups/", include("groups.api.urls")),

    path("api/activity/", include("activity.api.urls")),
    path("api/almanac/", include("almanac.api.urls")),
    path("api/assets/", include("assets.api.urls")),
    path("api/bazaar/", include("bazaar.api.urls")),
    path("api/chat/", include("chat.api.urls")),
    path("api/commons/", include("commons.api.urls")),
    path("api/classifications/", include("classifications.api.urls")),
    path("api/feedback/", include("feedback.api.urls")),
    path("api/collections/", include("stackroom.api.collection_urls")),  # Collection curation layer
    path("api/dispatch/", include("dispatch.api.urls")),
    path("api/gristmill/", include("gristmill.api.urls")),
    path("api/identity/", include("identity.api.urls")),
    path("api/inkwell/", include("inkwell.api.urls")),
    path("api/lanternmail/", include("lanternmail.api.urls")),  # Global lanternmail endpoints
    path("api/lists/", include("lists.api.urls")),
    path("api/mindmaps/", include("mindmap.api.urls")),
    path("api/livewire/", include("livewire.api.urls")),
    path("api/ops/", include("ops.api.urls")),
    path("api/projects/", include("projects.api.urls")),
    path("api/appearance/", include("appearance.api.urls")),
    path("api/stackroom/", include("stackroom.api.urls")),

    path("api/threadworks/", include("threadworks.api.urls")),
    path("api/work-sessions/", include("worksessions.api.urls")),
    path("api/writing/", include("writing.api.urls")),
    path("api/storyline/", include("writing.api.storyline_urls")),
    path("api/distribution/", include("distribution.api.urls")),
    path("api/concord/", include("concord.api.urls")),  # Audio transcription/interpretation
    path("api/earthlab/", include("earthlab.api.urls")),  # EarthLab courses/lessons
    path("api/spellbook/", include("spellbook.api.urls")),  # Shared spell dictionary

    # === PHASE 4 ENDPOINTS ===

    # Push token registration
    path("api/push/", include("users.api.urls")),

    # Broadcast (group announcements, steward-authored)
    path("api/broadcast/", include("broadcast.api.urls")),

    # Workbench (Review Queue, MillDrafts)
    path("api/workbench/", include("fundamentals.api.urls")),

    # === END PHASE 4 ENDPOINTS ===

    # DRF Router endpoints
    path("api/", include(router.urls)),
]

# ============================================================================
# DEFERRED ENDPOINTS (Add back in later phases):
# - path("api/groups", include("groups.api.urls"))
# - path("api/ai/", include("ai.api.urls"))

# - path("api/writing/", include("writing.api.urls"))
# - path("api/assets", include("assets.api.urls"))
# - path("api/identity/", include("identity.api.urls"))
# - And many others...
# ============================================================================
