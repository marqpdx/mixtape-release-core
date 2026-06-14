from django.urls import path
from . import views

urlpatterns = [
    path("room-token/", views.room_token, name="bridge-room-token"),
]
