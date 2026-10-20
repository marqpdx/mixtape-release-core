from django.urls import path
from . import views

urlpatterns = [
    path("weaves/", views.start, name="shuttle-start-interpretation"),
    path("weaves/<uuid:action_run_id>/", views.detail, name="shuttle-findings"),
    path("weaves/<uuid:action_run_id>/interpret/", views.execute, name="shuttle-interpret"),
    path("weaves/<uuid:action_run_id>/correct/", views.correct, name="shuttle-correct"),
    path("weaves/<uuid:action_run_id>/build-packet/", views.build_packet_view, name="shuttle-build-packet"),
    path("weaves/<uuid:action_run_id>/confirm/", views.confirm_view, name="shuttle-confirm"),
    path("weaves/<uuid:action_run_id>/keep-in-notebook/", views.keep_in_notebook, name="shuttle-keep-in-notebook"),
]
