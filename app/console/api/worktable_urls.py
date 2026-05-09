from django.urls import path
from .views import WorkTableStreamView

urlpatterns = [
    path("", WorkTableStreamView.as_view(), name="worktable-stream"),
]
