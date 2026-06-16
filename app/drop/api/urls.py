# drop/api/urls.py
from django.urls import path

from .views import GroupDropArchiveView, GroupDropsListCreateView

urlpatterns = [
    path("", GroupDropsListCreateView.as_view(), name="group-drops-list-create"),
    path("<uuid:drop_id>/archive/", GroupDropArchiveView.as_view(), name="group-drop-archive"),
]
