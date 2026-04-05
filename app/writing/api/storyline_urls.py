# writing/api/storyline_urls.py

from django.urls import path

from .storyline_views import GroupStorylineFeedView, PersonalStorylineFeedView

app_name = "storyline"

urlpatterns = [
    path("groups/<uuid:group_id>", GroupStorylineFeedView.as_view(), name="group-storyline"),
    path("users/<uuid:user_id>", PersonalStorylineFeedView.as_view(), name="personal-storyline"),
]
