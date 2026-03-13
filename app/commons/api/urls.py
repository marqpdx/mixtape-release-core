# commons/api/urls.py

from django.urls import path

from . import views

urlpatterns = [
    # CommonsItem CRUD
    path("items", views.CommonsItemListCreateView.as_view(), name="commons-list-create"),
    path("items/<uuid:pk>", views.CommonsItemDetailView.as_view(), name="commons-detail"),

    # Curation workflow
    path("items/<uuid:pk>/advance", views.CommonsItemAdvanceView.as_view(), name="commons-advance"),
    path("items/<uuid:pk>/reject", views.CommonsItemRejectView.as_view(), name="commons-reject"),

    # Filaments
    path("items/<uuid:pk>/filaments", views.FilamentListCreateView.as_view(), name="commons-filaments"),
    path("filaments/<uuid:pk>", views.FilamentDeleteView.as_view(), name="filament-delete"),
]
