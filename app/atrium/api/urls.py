# atrium/api/urls.py

from django.urls import path

from .views import (
    AtriumMeDialogueExchangeView,
    AtriumMeDialogueView,
    AtriumSponsorContextView,
    DialogueCompactView,
    DialogueContextView,
    DialogueCreateView,
    DialogueDistillateView,
    DialogueDistillView,
    DialogueEntryListView,
    DialogueEntryStreamView,
    DialogueExchangeView,
    DialogueInitiativeLogView,
    DialogueListView,
    DialogueResetView,
    DialogueUpdateView,
    DialogueWarmView,
    InitiativeOpenView,
    AtriumStartView,
)

urlpatterns = [
    path("me/dialogue", AtriumMeDialogueView.as_view(), name="atrium-me-dialogue"),
    path("me/dialogue/exchange", AtriumMeDialogueExchangeView.as_view(), name="atrium-me-dialogue-exchange"),
    path("sponsor-context/", AtriumSponsorContextView.as_view(), name="atrium-sponsor-context"),
    path("me/start", AtriumStartView.as_view(), name="atrium-me-start"),
    path("initiatives/<uuid:initiative_id>/open", InitiativeOpenView.as_view(), name="atrium-initiative-open"),
    # Old path, until the page using /open is deployed.
    path("initiatives/<uuid:initiative_id>/dialogue-zero", InitiativeOpenView.as_view(), name="atrium-initiative-dialogue-zero"),
    path("dialogues/", DialogueListView.as_view(), name="atrium-dialogue-list"),
    path("dialogues/new", DialogueCreateView.as_view(), name="atrium-dialogue-create"),
    path("dialogues/<uuid:dialogue_id>/", DialogueUpdateView.as_view(), name="atrium-dialogue-update"),
    path("dialogues/<uuid:dialogue_id>/entries/", DialogueEntryListView.as_view(), name="atrium-dialogue-entries"),
    path("dialogues/<uuid:dialogue_id>/entries/<uuid:entry_id>/stream", DialogueEntryStreamView.as_view(), name="atrium-dialogue-entry-stream"),
    path("dialogues/<uuid:dialogue_id>/initiative-log/", DialogueInitiativeLogView.as_view(), name="atrium-dialogue-initiative-log"),
    path("dialogues/<uuid:dialogue_id>/context/", DialogueContextView.as_view(), name="atrium-dialogue-context"),
    path("dialogues/<uuid:dialogue_id>/exchange", DialogueExchangeView.as_view(), name="atrium-dialogue-exchange"),
    path("dialogues/<uuid:dialogue_id>/warm", DialogueWarmView.as_view(), name="atrium-dialogue-warm"),
    path("dialogues/<uuid:dialogue_id>/compact", DialogueCompactView.as_view(), name="atrium-dialogue-compact"),
    path("dialogues/<uuid:dialogue_id>/distill", DialogueDistillView.as_view(), name="atrium-dialogue-distill"),
    path("dialogues/<uuid:dialogue_id>/distillates/<uuid:distillate_id>", DialogueDistillateView.as_view(), name="atrium-dialogue-distillate"),
    path("dialogues/<uuid:dialogue_id>/reset", DialogueResetView.as_view(), name="atrium-dialogue-reset"),
]
