# switchboard/api/urls.py

from django.urls import path

from .views import classify_async_proxy, summarize_async_proxy

urlpatterns = [
    path("summarize/async", summarize_async_proxy, name="switchboard-summarize-async"),
    path("classify/async", classify_async_proxy, name="switchboard-classify-async"),
]
