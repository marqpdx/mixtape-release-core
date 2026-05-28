from django.urls import path

from .views import (
    LivingBookDetailView,
    LivingBookListCreateView,
    LivingBookTreeView,
    LivingBookAccumulatedView,
    LivingBookNodeAddView,
    LivingBookNodeCreateAddView,
    LivingBookRootReorderView,
    LivingBookNodeReorderView,
    LivingBookNodeRemoveView,
    LivingBookContextView,
)
from .branch_views import (
    BranchListCreateView,
    BranchDetailView,
    BranchSendInvitationView,
    LeafClusterListCreateView,
    LeafClusterDetailView,
)

urlpatterns = [
    path("", LivingBookListCreateView.as_view()),
    path("<uuid:pk>/", LivingBookDetailView.as_view()),
    path("<uuid:pk>/tree/", LivingBookTreeView.as_view()),
    path("<uuid:pk>/accumulated/", LivingBookAccumulatedView.as_view()),
    path("<uuid:pk>/nodes/", LivingBookNodeAddView.as_view()),
    path("<uuid:pk>/nodes/create/", LivingBookNodeCreateAddView.as_view()),
    path("<uuid:pk>/nodes/reorder/", LivingBookRootReorderView.as_view()),
    path("<uuid:pk>/nodes/<uuid:piece_id>/reorder/", LivingBookNodeReorderView.as_view()),
    path("<uuid:pk>/nodes/<uuid:piece_id>/", LivingBookNodeRemoveView.as_view()),
    path("<uuid:pk>/context/<uuid:piece_id>/", LivingBookContextView.as_view()),
    # Branch + LeafCluster (Phase 3)
    path("<uuid:pk>/branches/", BranchListCreateView.as_view()),
    path("<uuid:pk>/branches/<uuid:branch_id>/", BranchDetailView.as_view()),
    path("<uuid:pk>/branches/<uuid:branch_id>/send-invitation/", BranchSendInvitationView.as_view()),
    path("<uuid:pk>/branches/<uuid:branch_id>/leaf-clusters/", LeafClusterListCreateView.as_view()),
    path("<uuid:pk>/branches/<uuid:branch_id>/leaf-clusters/<uuid:lc_id>/", LeafClusterDetailView.as_view()),
]
