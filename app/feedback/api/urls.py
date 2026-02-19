from django.urls import path

from . import views

urlpatterns = [
    path("beacons/<slug:key>", views.get_beacon, name="feedback-beacon"),
    path("items", views.create_feedback_item, name="feedback-item-create"),
    path("items/summary", views.feedback_summary, name="feedback-item-summary"),
]
