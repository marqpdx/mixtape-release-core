from django.urls import path
from . import views

urlpatterns = [
    path("weaves/", views.start, name="shuttle-start-interpretation"),
    path("weaves/<uuid:action_run_id>/", views.detail, name="shuttle-findings"),
    path("weaves/<uuid:action_run_id>/interpret/", views.execute, name="shuttle-interpret"),
    path("weaves/<uuid:action_run_id>/correct/", views.correct, name="shuttle-correct"),
]
