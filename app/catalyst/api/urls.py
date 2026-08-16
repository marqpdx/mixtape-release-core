# catalyst/api/urls.py

from django.urls import path
from .views import MaterializeRegistersView

urlpatterns = [
    path(
        "groups/<slug:slug>/materialize-registers/",
        MaterializeRegistersView.as_view(),
        name="catalyst-materialize-registers",
    ),
]
