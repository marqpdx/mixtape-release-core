# earthlab/api/urls.py
from django.urls import path
from . import views

# parent: api/earthlab/

urlpatterns = [
    path('<slug:group_slug>/courses', views.list_courses),
    path('<slug:group_slug>/lessons', views.list_lessons),
]
