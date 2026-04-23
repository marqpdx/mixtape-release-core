from django.urls import path

from .views import (
    LivingBookDetailView,
    LivingBookListCreateView,
    LivingBookTreeView,
    LivingBookAccumulatedView,
    LivingBookNodeAddView,
    LivingBookNodeCreateAddView,
    LivingBookNodeReorderView,
    LivingBookNodeRemoveView,
    LivingBookContextView,
)

urlpatterns = [
    path("", LivingBookListCreateView.as_view()),
    path("<uuid:pk>/", LivingBookDetailView.as_view()),
    path("<uuid:pk>/tree/", LivingBookTreeView.as_view()),
    path("<uuid:pk>/accumulated/", LivingBookAccumulatedView.as_view()),
    path("<uuid:pk>/nodes/", LivingBookNodeAddView.as_view()),
    path("<uuid:pk>/nodes/create/", LivingBookNodeCreateAddView.as_view()),
    path("<uuid:pk>/nodes/<uuid:piece_id>/reorder/", LivingBookNodeReorderView.as_view()),
    path("<uuid:pk>/nodes/<uuid:piece_id>/", LivingBookNodeRemoveView.as_view()),
    path("<uuid:pk>/context/<uuid:piece_id>/", LivingBookContextView.as_view()),
]
