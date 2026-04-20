from django.urls import path

from .views import IntakeQuestionsView, IntakeSubmittedView, IntakeWelcomeView

urlpatterns = [
    path("intake/<uuid:token>/", IntakeWelcomeView.as_view(), name="intake-welcome"),
    path("intake/<uuid:token>/questions/", IntakeQuestionsView.as_view(), name="intake-questions"),
    path("intake/<uuid:token>/submitted/", IntakeSubmittedView.as_view(), name="intake-submitted"),
]
