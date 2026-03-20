# users/api/urls.py
from django.urls import path
from .views import PushTokenRegisterView

urlpatterns = [
    path("register/", PushTokenRegisterView.as_view(), name="push-token-register"),
]
