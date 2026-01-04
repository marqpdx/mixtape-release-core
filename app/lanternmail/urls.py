# lantern/urls.py

from django.urls import path
from . import views

# parent path: api/lantern/

urlpatterns = [
    # Group-based mailing list endpoints
    path("groups/<uuid:group_id>/mailing-list", views.create_group_mailing_list, name="create-group-mailing-list"),
    path("groups/<uuid:group_id>/mailing-lists", views.get_group_mailing_lists, name="get-group-mailing-lists"),

    path("groups/<uuid:group_id>/mailing-lists/<int:list_id>/subscribers", views.get_group_members_with_subscription_status, name="group-list-members"),
    path("groups/<uuid:group_id>/mailing-lists/subscribers", views.get_group_members_all_lists, name="group-all-members"),

    path("mailing-lists/<int:list_id>/invitations", views.send_list_invitations, name="send-list-invitations"),

    path("mailing-lists", views.list_user_mailing_lists, name="list-user-mailing-lists"),

    # Optional: Individual list management
    path("mailing-lists/<int:list_id>", views.get_mailing_list_detail, name="mailing-list-detail"),
    path("mailing-lists/<int:list_id>/toggle", views.toggle_mailing_list, name="toggle-mailing-list"),
]

