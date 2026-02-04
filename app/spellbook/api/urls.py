# spellbook/api/urls.py

from django.urls import path

from spellbook.api.views import (
    SpellCorrectionDetailView,
    SpellCorrectionListView,
    SpellCorrectionUsageView,
    SpellSuggestionApproveView,
    SpellSuggestionListView,
    SpellSuggestionRejectView,
)

app_name = "spellbook"

urlpatterns = [
    # Corrections (the approved dictionary)
    path("", SpellCorrectionListView.as_view(), name="correction-list"),
    path("<uuid:correction_id>/", SpellCorrectionDetailView.as_view(), name="correction-detail"),
    path("<uuid:correction_id>/record-usage/", SpellCorrectionUsageView.as_view(), name="correction-usage"),

    # Suggestions (user-submitted, awaiting review)
    path("suggestions/", SpellSuggestionListView.as_view(), name="suggestion-list"),
    path("suggestions/<uuid:suggestion_id>/approve/", SpellSuggestionApproveView.as_view(), name="suggestion-approve"),
    path("suggestions/<uuid:suggestion_id>/reject/", SpellSuggestionRejectView.as_view(), name="suggestion-reject"),
]
