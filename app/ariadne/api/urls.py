from django.urls import path

from .views import (
    ConceptLookupView,
    LatestRunView,
    PacketDetailView,
    RunCandidateListView,
    RunDecisionView,
    RunDetailView,
    RunPacketAssembleView,
)

urlpatterns = [
    path("runs/latest/", LatestRunView.as_view(), name="ariadne-run-latest"),
    path("runs/<uuid:run_id>/", RunDetailView.as_view(), name="ariadne-run-detail"),
    path("runs/<uuid:run_id>/candidates/", RunCandidateListView.as_view(), name="ariadne-run-candidates"),
    path("runs/<uuid:run_id>/decisions/", RunDecisionView.as_view(), name="ariadne-run-decisions"),
    path("runs/<uuid:run_id>/packets/", RunPacketAssembleView.as_view(), name="ariadne-run-packets"),
    path("packets/<uuid:packet_id>/", PacketDetailView.as_view(), name="ariadne-packet-detail"),
    path("concepts/", ConceptLookupView.as_view(), name="ariadne-concept-lookup"),
    path("concepts/<uuid:concept_id>/", ConceptLookupView.as_view(), name="ariadne-concept-detail"),
]
