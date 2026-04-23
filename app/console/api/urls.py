from django.urls import path

from .views import OrientationView, ReentryView, SignalsView, StewardshipView

urlpatterns = [
    path("reentry/", ReentryView.as_view(), name="console-reentry"),
    path("signals/", SignalsView.as_view(), name="console-signals"),
    path("orientation/", OrientationView.as_view(), name="console-orientation"),
    path("stewardship/", StewardshipView.as_view(), name="console-stewardship"),
]
