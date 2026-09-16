from django.urls import path

from clio.api.views import (
    KeeperDeregisterView,
    KeeperRegisterView,
    KeeperRegistryListView,
    KeeperRouteView,
)

urlpatterns = [
    path("keepers/register", KeeperRegisterView.as_view(), name="clio-keeper-register"),
    path("keepers/<slug:keeper_id>/deregister", KeeperDeregisterView.as_view(), name="clio-keeper-deregister"),
    path("keepers", KeeperRegistryListView.as_view(), name="clio-keeper-registry"),
    path("route", KeeperRouteView.as_view(), name="clio-keeper-route"),
]
