from django.urls import path

from . import views

urlpatterns = [
    path("beacons/<slug:key>", views.get_beacon, name="feedback-beacon"),
    path("items", views.feedback_items, name="feedback-items"),
    path("checklist", views.feedback_checklist, name="feedback-checklist"),
    path("items/summary", views.feedback_summary, name="feedback-item-summary"),
]
