from django.urls import path

from clio.api.views import (
    KeeperDeregisterView,
    KeeperFindingListView,
    KeeperFindingSubmitView,
    KeeperRegisterView,
    KeeperRegistryListView,
    KeeperRouteView,
)

urlpatterns = [
    path("keepers/register", KeeperRegisterView.as_view(), name="clio-keeper-register"),
    # str, not slug: AD-10's own keeper_id example ("count-nag-keeper.junk-pile")
    # contains a dot, which Django's slug converter rejects.
    path("keepers/<str:keeper_id>/deregister", KeeperDeregisterView.as_view(), name="clio-keeper-deregister"),
    path("keepers", KeeperRegistryListView.as_view(), name="clio-keeper-registry"),
    path("route", KeeperRouteView.as_view(), name="clio-keeper-route"),
    path("findings", KeeperFindingSubmitView.as_view(), name="clio-keeper-finding-submit"),
    path("findings/inspect", KeeperFindingListView.as_view(), name="clio-keeper-finding-list"),
]
