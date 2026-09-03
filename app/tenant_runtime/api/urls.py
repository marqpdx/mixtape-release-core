from django.urls import path

from .views import (
    TenantCodexRuntimeLoginStatusView,
    TenantCodexRuntimeLogoutView,
    TenantCodexRuntimeStartLoginView,
    TenantCodexRuntimeStatusView,
    TenantRuntimeLoginStatusView,
    TenantRuntimeStartLoginView,
    TenantRuntimeStatusView,
)

urlpatterns = [
    path(
        "groups/<slug:slug>/status/",
        TenantRuntimeStatusView.as_view(),
        name="tenant-runtime-status",
    ),
    path(
        "groups/<slug:slug>/start-login/",
        TenantRuntimeStartLoginView.as_view(),
        name="tenant-runtime-start-login",
    ),
    path(
        "groups/<slug:slug>/login-status/",
        TenantRuntimeLoginStatusView.as_view(),
        name="tenant-runtime-login-status",
    ),
    path(
        "groups/<slug:slug>/codex/status/",
        TenantCodexRuntimeStatusView.as_view(),
        name="tenant-codex-runtime-status",
    ),
    path(
        "groups/<slug:slug>/codex/start-login/",
        TenantCodexRuntimeStartLoginView.as_view(),
        name="tenant-codex-runtime-start-login",
    ),
    path(
        "groups/<slug:slug>/codex/login-status/",
        TenantCodexRuntimeLoginStatusView.as_view(),
        name="tenant-codex-runtime-login-status",
    ),
    path(
        "groups/<slug:slug>/codex/logout/",
        TenantCodexRuntimeLogoutView.as_view(),
        name="tenant-codex-runtime-logout",
    ),
]
