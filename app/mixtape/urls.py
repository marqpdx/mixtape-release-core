# mixtape/urls.py

from django.contrib import admin
from django.urls import include, path
from rest_framework import routers
from . import views

# from accounts.api import views as userViews  # Deferred - UserViewSet needs Phase 2 serializers

router = routers.DefaultRouter()
# router.register(r'api/users', userViews.UserViewSet)  # Deferred to Phase 2+

# ============================================================================
# PHASE 1: MINIMAL URL CONFIGURATION
# ============================================================================
# Only authentication and member endpoints enabled
# Other endpoints will be added back in future phases
# ============================================================================

urlpatterns = [
    # Django admin
    path('admin/', admin.site.urls),

    # DRF browsable API login
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),

    # Health check (for monitoring, tests, and deployment)
    path('health/', views.health_check, name='health_check'),

    # CSRF token endpoint (for frontend auth initialization)
    path('api/csrf/', views.csrf_token_view, name='csrf_token'),

    # === PHASE 1 ENDPOINTS ===

    # Authentication
    path('api/auth/', include('accounts.api.auth_urls')),
    # Endpoints: /api/auth/token, /api/auth/token/refresh, /api/auth/logout, /api/auth/me

    # Members (User + Profile combined)
    path('api/members/', include('profiles.api.urls')),
    # Endpoints: /api/members/, /api/members/<slug>

    # === END PHASE 1 ENDPOINTS ===

    # === PHASE 2 ENDPOINTS ===

    # Groups
    path('api/groups', include('groups.api.urls')),
    # Endpoints: /api/groups, /api/groups/<slug>, /api/groups/<slug>/members, etc.

    # === END PHASE 2 ENDPOINTS ===
]
# urlpatterns += router.urls  # Deferred - no router endpoints in Phase 1

# ============================================================================
# DEFERRED ENDPOINTS (Add back in later phases):
# - path('api/groups', include('groups.api.urls'))
# - path('api/ai/', include('ai.api.urls'))
# - path('api/chat/', include('chat.api.urls'))
# - path('api/writing/', include('writing.api.urls'))
# - path('api/assets', include('assets.api.urls'))
# - path("api/identity/", include("identity.api.urls"))
# - And many others...
# ============================================================================