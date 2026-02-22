# activity/api/urls.py

from django.urls import path

from activity.api.views import (
    GroupPulseView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationPreferenceView,
    NotificationSummaryView,
    NotificationDismissView,
)


# parent path: api/activity

urlpatterns = [
    path("", NotificationListView.as_view(), name="notifications-list"),
    path("summary", NotificationSummaryView.as_view(), name="notifications-summary"),
    path("mark-read", NotificationMarkReadView.as_view(), name="notifications-mark-read"),
    path("mark-all-read", NotificationMarkAllReadView.as_view(), name="notifications-mark-all-read"),
    path("preferences", NotificationPreferenceView.as_view(), name="notifications-preferences"),
    path("group-pulse", GroupPulseView.as_view(), name="group-pulse"),
    path("<uuid:notification_id>", NotificationDismissView.as_view(), name="notifications-dismiss"),
]
