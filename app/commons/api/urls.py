# commons/api/urls.py

from django.urls import path

from . import views

urlpatterns = [
    # CommonsItem CRUD
    path("items", views.CommonsItemListCreateView.as_view(), name="commons-list-create"),
    path("items/<uuid:pk>", views.CommonsItemDetailView.as_view(), name="commons-detail"),

    # Filaments
    path("items/<uuid:pk>/filaments", views.FilamentListCreateView.as_view(), name="commons-filaments"),
    path("filaments/<uuid:pk>", views.FilamentDeleteView.as_view(), name="filament-delete"),
]
