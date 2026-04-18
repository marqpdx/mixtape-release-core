from django.urls import path

from .views import ReadinessView

urlpatterns = [
    path("<slug:piece_slug>/readiness/", ReadinessView.as_view()),
]
