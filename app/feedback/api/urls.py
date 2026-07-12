# feedback/api/urls.py

from django.urls import path

from . import views

urlpatterns = [
    path("beacons/<slug:key>", views.get_beacon, name="feedback-beacon"),
    path("items", views.feedback_items, name="feedback-items"),
    path("items/<str:item_id>", views.update_feedback_item, name="feedback-item-update"),
    path("checklist", views.feedback_checklist, name="feedback-checklist"),
    path("items/summary", views.feedback_summary, name="feedback-item-summary"),
    path("upload-voice", views.upload_feedback_voice, name="feedback-upload-voice"),
    path("upload-attachment", views.upload_feedback_attachment, name="feedback-upload-attachment"),
    path("voice-status/<str:voice_upload_id>", views.feedback_voice_status, name="feedback-voice-status"),
    path("mindful-brilliance/contact", views.mindful_brilliance_contact, name="mb-contact"),
]
