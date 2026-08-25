from django.urls import path

from .views import (
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
]
