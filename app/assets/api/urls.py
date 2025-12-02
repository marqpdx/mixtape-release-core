# mixtape/assets/api/urls.py

from django.urls import path
from . import views

# parent; api/assets

urlpatterns = [
    path("", views.AssetListCreateView.as_view(), name="asset-list-create"),
    path("<uuid:id>", views.AssetRetrieveUpdateView.as_view(), name="asset-detail"),

    # ===== SPONSOR-AGNOSTIC ENDPOINTS =====

    # Simple image upload (profile/background images, no DB records)
    path("upload", views.SponsorImageUploadView.as_view(), name="sponsor-image-upload"),

    # Managed asset upload (full Asset records with metadata, privacy, etc.)
    path("managed/upload", views.SponsorAssetUploadView.as_view(), name="sponsor-asset-upload"),
    path("managed/list", views.SponsorAssetListView.as_view(), name="sponsor-asset-list"),
    path("managed/folders", views.SponsorAssetFolderListView.as_view(), name="sponsor-asset-folders"),
    path("managed/<uuid:asset_id>/presign", views.SponsorAssetPresignView.as_view(), name="sponsor-asset-presign"),

    # ===== GROUP-SPECIFIC ENDPOINTS (Deprecated - use sponsor-agnostic above) =====

    path("groups/<uuid:group_id>/upload", views.GroupAssetUploadView.as_view(), name="group-asset-upload"),
    path("groups/<uuid:group_id>/assets", views.GroupAssetListView.as_view(), name="group-asset-list"),
    path("groups/<uuid:group_id>/folders", views.GroupAssetFolderListView.as_view(), name="group-asset-folders"),
    path("group-assets/<int:group_asset_id>/presign", views.GroupAssetPresignView.as_view(), name="group-asset-presign"),

    # ===== LEGACY ENDPOINTS (Deprecated - use sponsor-agnostic above) =====

    path("entity-image/<str:entity_type>/<str:entity_id>/<str:image_type>",
        views.EntityImageUploadView.as_view(),
        name="entity-image-upload",
    ),

]
