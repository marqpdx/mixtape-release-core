# app/mixtape/urls.py

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from rest_framework import routers

from accounts.api.views import UserViewSet
from groups.api.files_views import MeFilesListView, MeFileDeleteView
from initiatives.api.urls import action_run_patterns, agent_object_patterns, aperture_patterns, me_patterns, mobile_command_patterns, radar_patterns, worktable_group_patterns
from prospects.api.urls import intake_patterns, internal_patterns
from profiles.api.profile_revamp_urls import public_profile_patterns, me_profile_patterns

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

    # Profile revamp — public read + owner write
    path("api/profiles/", include(public_profile_patterns)),
    path("api/me/profile/", include(me_profile_patterns)),

    # Personal file library (stackroom)
    path("api/me/files/", MeFilesListView.as_view(), name="me-files-list"),
    path("api/me/files/<uuid:source_file_id>/", MeFileDeleteView.as_view(), name="me-file-delete"),

    # === END PHASE 1 ENDPOINTS ===

    # Public API (anonymous + logged-in reader surface)
    path("api/public/", include("public_api.urls")),

    # === PHASE 2 ENDPOINTS ===

    # Business hub (Supplier, SupplyRequest, FixItem)
    path("api/business/", include("business.api.urls")),

    # WorkTable group-scoped buckets (reminders, tasks)
    path("api/worktable/groups/", include(worktable_group_patterns)),

    # WorkTable stream + prose endpoints (WT-B1/B2, WT-B6)
    path("api/worktable/", include("console.api.worktable_urls")),

    # Groups
    path("api/groups/", include("groups.api.urls")),
    path("api/initiatives/", include(aperture_patterns)),
    path("api/initiatives/", include(action_run_patterns)),
    path("api/initiatives/", include(agent_object_patterns)),
    path("api/initiatives/", include(me_patterns)),
    path("api/initiatives/", include(mobile_command_patterns)),
    path("api/initiatives/", include(radar_patterns)),

    path("api/activity/", include("activity.api.urls")),
    path("api/almanac/", include("almanac.api.urls")),
    path("api/assets/", include("assets.api.urls")),
    path("api/bazaar/", include("bazaar.api.urls")),
    path("api/chat/", include("chat.api.urls")),
    path("api/commons/", include("commons.api.urls")),
    path("api/classifications/", include("classifications.api.urls")),
    path("api/feedback/", include("feedback.api.urls")),
    path("api/files/", include("files.api.urls")),
    path("api/collections/", include("curation.urls")),  # Collection curation layer (CP5)
    path("api/stackroom/", include("curation.stackroom_urls")),  # Stackroom source-file proxy
    path("api/puddlejump/", include("puddlejump.urls")),  # Puddlejump library
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
    path("api/threadworks/", include("threadworks.api.urls")),
    path("api/work-sessions/", include("worksessions.api.urls")),
    path("api/writing/", include("writing.api.urls")),
    path("api/atelier/", include("atelier.api.urls")),
    path("api/living-books/", include("living_book.api.urls")),
    path("api/console/", include("console.api.urls")),
    path("api/reading/", include("reading.api.urls")),
    path("api/switchboard/", include("switchboard.api.urls")),
    path("api/storyline/", include("writing.api.storyline_urls")),
    path("api/distribution/", include("distribution.api.urls")),
    path("api/studio/", include("studio.urls")),  # Studio — personal and group admin surface
    path("api/clio/", include("clio.urls")),  # Clio — Keeper registry/relay (Keeper ADR K-1)
    path("api/bridge/", include("bridge.api.urls")),              # Bridge — live gatherings
    path("api/concord/", include("concord.api.urls")),            # Audio transcription/interpretation
    path("api/media-capture/", include("media_capture.api.urls")),  # MediaCapture screencast pipeline
    path("api/earthlab/", include("earthlab.api.urls")),  # EarthLab courses/lessons
    path("api/spellbook/", include("spellbook.api.urls")),  # Shared spell dictionary

    # === PHASE 4 ENDPOINTS ===

    # Push token registration
    path("api/push/", include("users.api.urls")),

    # Broadcast (group announcements, steward-authored)
    path("api/broadcast/", include("broadcast.api.urls")),

    # Workbench (Review Queue, MillDrafts)
    path("api/workbench/", include("fundamentals.api.urls")),

    # Atrium — personal AI session surface
    path("api/atrium/", include("atrium.api.urls")),

    # Catalyst — Codex ingest and materialization
    path("api/catalyst/", include("catalyst.api.urls")),
    path("api/tenant-runtime/", include("tenant_runtime.api.urls")),

    # === END PHASE 4 ENDPOINTS ===

    # Prospects — public intake (token-gated, no auth)
    path("api/intake/", include(intake_patterns)),
    # Prospects — internal staff API
    path("api/", include(internal_patterns)),

    # Prospects — public Django template views
    path("", include("prospects.urls")),

    # DRF Router endpoints
    path("api/", include(router.urls)),
]

if getattr(settings, "OCR_SPIKE_ENABLED", False):
    urlpatterns.append(path("api/spikes/ocr/", include("ocr_spike.api.urls")))

# ============================================================================
# DEFERRED ENDPOINTS (Add back in later phases):
# - path("api/groups", include("groups.api.urls"))
# - path("api/ai/", include("ai.api.urls"))

# - path("api/writing/", include("writing.api.urls"))
# - path("api/assets", include("assets.api.urls"))
# - path("api/identity/", include("identity.api.urls"))
# - And many others...
# ============================================================================
