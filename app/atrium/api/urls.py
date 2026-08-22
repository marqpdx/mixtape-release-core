# atrium/api/urls.py

from django.urls import path

from .views import (
    AtriumSessionListView,
    AtriumSessionCreateView,
    AtriumSessionEntryListView,
    AtriumSessionContextView,
    AtriumSessionUpdateView,
    AtriumSessionExchangeView,
    AtriumSessionWarmView,
    AtriumSessionCompactView,
)

urlpatterns = [
    path("sessions/", AtriumSessionListView.as_view(), name="atrium-session-list"),
    path("sessions/new", AtriumSessionCreateView.as_view(), name="atrium-session-create"),
    path("sessions/<uuid:session_id>/", AtriumSessionUpdateView.as_view(), name="atrium-session-update"),
    path("sessions/<uuid:session_id>/entries/", AtriumSessionEntryListView.as_view(), name="atrium-session-entries"),
    path("sessions/<uuid:session_id>/context/", AtriumSessionContextView.as_view(), name="atrium-session-context"),
    path("sessions/<uuid:session_id>/exchange", AtriumSessionExchangeView.as_view(), name="atrium-session-exchange"),
    path("sessions/<uuid:session_id>/warm", AtriumSessionWarmView.as_view(), name="atrium-session-warm"),
    path("sessions/<uuid:session_id>/compact", AtriumSessionCompactView.as_view(), name="atrium-session-compact"),
]
