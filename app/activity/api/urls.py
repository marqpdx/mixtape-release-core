# activity/api/urls.py

from django.urls import path

from activity.api.views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationSummaryView,
)


# parent path: api/activity

urlpatterns = [
    path("", NotificationListView.as_view(), name="notifications-list"),
    path("/summary", NotificationSummaryView.as_view(), name="notifications-summary"),
    path("/mark-read", NotificationMarkReadView.as_view(), name="notifications-mark-read"),
    path("/mark-all-read", NotificationMarkAllReadView.as_view(), name="notifications-mark-all-read"),
]
