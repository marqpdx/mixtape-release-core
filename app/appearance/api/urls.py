# appearance/api/urls.py

"""
Appearance API endpoints
Group-scoped theme management
"""

from django.urls import path

from . import views

app_name = "appearance"

urlpatterns = [
    path("groups/<slug:slug>/themes", views.GroupThemeSettingsView.as_view(), name="group-theme-settings"),
]
