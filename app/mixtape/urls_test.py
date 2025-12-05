# mixtape-back/mixtape/urls_test.py

from api import test_views
from django.urls import path

# Import your regular URLs
from .urls import urlpatterns as regular_urlpatterns


# Add test endpoints to regular URLs
urlpatterns = regular_urlpatterns + [
    # Email helpers
    path("api/test/last-email/", test_views.last_email, name="test-last-email"),
    path("api/test/clear-emails/", test_views.clear_emails, name="test-clear-emails"),

    # Test data creation
    path("api/test/create-user/", test_views.create_user, name="test-create-user"),
    path("api/test/create-group/", test_views.create_group, name="test-create-group"),
    path("api/test/add-member/", test_views.add_member, name="test-add-member"),
    path("api/test/cleanup/", test_views.cleanup, name="test-cleanup"),
]
