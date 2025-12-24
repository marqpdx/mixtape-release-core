# gristmill/api/urls.py
from django.urls import path
from . import views

# parent: api/gristmill/

urlpatterns = [
    path('parse', views.parse_view),
    path('drafts', views.save_draft_view),
    path('drafts', views.list_drafts_view),
    path('drafts/<uuid:draft_id>/promote', views.promote_draft_view),
]
