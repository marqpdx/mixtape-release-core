from django.urls import path
from .views import WorkTableProseView, WorkTableStreamView

urlpatterns = [
    path("stream/", WorkTableStreamView.as_view(), name="worktable-stream"),
    path("prose/", WorkTableProseView.as_view(), name="worktable-prose"),
]
