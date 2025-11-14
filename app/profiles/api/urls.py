# profiles/api/urls.py

from django.urls import path
from .views import MemberListView, MemberDetailView

# /api/members
urlpatterns = [
    path('', MemberListView.as_view(), name='member-list'),
    path('<slug:slug>', MemberDetailView.as_view(), name='member-detail'),
]
