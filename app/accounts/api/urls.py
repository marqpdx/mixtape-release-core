# accounts/api/urls.py

from django.urls import path

from groups.api.views import UserGroupsView

from . import jwt_views, views


# api/user

urlpatterns = [
    path("csrf", views.csrf, name="csrf-token"),
    path("signup", views.user_create_view, name="user-register"),
    path("me", views.CurrentUserIdentity.as_view(), name="me"),
    path("token", jwt_views.Login.as_view(), name="token"),
    path("token/refresh", jwt_views.RefreshToken.as_view(), name="token-refresh"),

    # TODO move this to groups/api/urls.py
    path("groups", UserGroupsView.as_view(), name="user-groups-list"),

    # needed?
    path("logout", jwt_views.Logout.as_view(), name="logout"),
]
