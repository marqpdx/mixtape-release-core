# switchboard/api/urls.py

from django.urls import path

from .views import summarize_async_proxy

urlpatterns = [
    path("summarize/async", summarize_async_proxy, name="switchboard-summarize-async"),
]
