# atrium/api/urls.py

from django.urls import path

from .views import AtriumSessionListView

urlpatterns = [
    path("sessions/", AtriumSessionListView.as_view(), name="atrium-session-list"),
]
