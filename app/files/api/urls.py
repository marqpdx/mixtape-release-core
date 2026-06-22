# files/api/urls.py

from django.urls import path

from .views import StoredFileServeView

app_name = "files"

# parent url: api/files/
urlpatterns = [
    path("<uuid:pk>/serve", StoredFileServeView.as_view(), name="storedfile-serve"),
]
