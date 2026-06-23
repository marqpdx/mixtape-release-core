# atrium/api/urls.py

from django.urls import path

from .views import (
    AtriumSessionListView,
    AtriumSessionCreateView,
    AtriumSessionExchangeView,
)

urlpatterns = [
    path("sessions/", AtriumSessionListView.as_view(), name="atrium-session-list"),
    path("sessions/new", AtriumSessionCreateView.as_view(), name="atrium-session-create"),
    path("sessions/<uuid:session_id>/exchange", AtriumSessionExchangeView.as_view(), name="atrium-session-exchange"),
]
