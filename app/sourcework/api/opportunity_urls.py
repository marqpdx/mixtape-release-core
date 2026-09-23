from django.urls import path

from .opportunity_views import (
    OpportunityApplicationDraftPDFView,
    OpportunityApplicationDraftView,
    OpportunityCandidateDetailsView,
    OpportunityCandidateStateView,
    OpportunityProfileView,
    OpportunityQueryPlanView,
    OpportunitySearchRunListCreateView,
)


urlpatterns = [
    path("profile", OpportunityProfileView.as_view(), name="opportunity-profile"),
    path("query-plan", OpportunityQueryPlanView.as_view(), name="opportunity-query-plan"),
    path("search-runs", OpportunitySearchRunListCreateView.as_view(), name="opportunity-search-runs"),
    path(
        "candidates/<uuid:data_id>/state",
        OpportunityCandidateStateView.as_view(),
        name="opportunity-candidate-state",
    ),
    path(
        "candidates/<uuid:data_id>/details",
        OpportunityCandidateDetailsView.as_view(),
        name="opportunity-candidate-details",
    ),
    path(
        "candidates/<uuid:data_id>/application-draft",
        OpportunityApplicationDraftView.as_view(),
        name="opportunity-application-draft",
    ),
    path(
        "candidates/<uuid:data_id>/application-draft/pdf",
        OpportunityApplicationDraftPDFView.as_view(),
        name="opportunity-application-draft-pdf",
    ),
]
