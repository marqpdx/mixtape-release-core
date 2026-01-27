# apps/identity/api/urls.py

from django.urls import path
from .views import (
    EmblemAvatarTypeListAPIView,
    EmblemAvatarPublicListAPIView,
    EmblemAvatarMineListAPIView,
    EmblemAvatarCreateAPIView,
    EmblemAvatarDetailAPIView,
    EmblemImageUploadView,
)

urlpatterns = [
    # Types
    path("emblem-avatar-types", EmblemAvatarTypeListAPIView.as_view(), name="emblem-avatar-type-list"),

    # Emblems
    path("emblem-avatars/public", EmblemAvatarPublicListAPIView.as_view(), name="emblem-avatar-public-list"),
    path("emblem-avatars/mine", EmblemAvatarMineListAPIView.as_view(), name="emblem-avatar-mine-list"),
    path("emblem-avatars", EmblemAvatarCreateAPIView.as_view(), name="emblem-avatar-create"),
    path("emblem-avatars/<uuid:pk>", EmblemAvatarDetailAPIView.as_view(), name="emblem-avatar-detail"),

    path("emblem-image", EmblemImageUploadView.as_view(), name="emblem-image-upload"
    ),
]
