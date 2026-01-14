# stackroom/api/collection_urls.py

"""
Collection API URLs

These URLs are intentionally separate from Stackroom URLs to maintain
the conceptual boundary between curation (meaning) and IR (truth).

Mount these under /api/collections/ (not /api/stackroom/)
"""

from django.urls import path
from stackroom.api.collection_views import (
    CollectionListView,
    CollectionDetailView,
    CollectionAvailableFilesView,
    CollectionAvailableDocumentsView,
    CollectionItemListView,
    CollectionItemDetailView,
    CollectionItemReorderView,
    CollectionItemCopyFromView,
    CollectionFileUploadView,
)
from stackroom.api.collection_search import CollectionTextSearchView

urlpatterns = [
    # Collection list
    path('', CollectionListView.as_view(), name='collection-list'),

    # Collection detail
    path('<uuid:collection_id>/', CollectionDetailView.as_view(), name='collection-detail'),

    # Text search (keyword search through content)
    path('<uuid:collection_id>/search/', CollectionTextSearchView.as_view(), name='collection-search'),

    # File upload (lightweight, no immediate ingestion)
    path('<uuid:collection_id>/upload/', CollectionFileUploadView.as_view(), name='collection-file-upload'),

    # Available files (for adding to Collection)
    path('<uuid:collection_id>/available-files/', CollectionAvailableFilesView.as_view(), name='collection-available-files'),

    # Available documents (WritingPieces)
    path('<uuid:collection_id>/available-documents/', CollectionAvailableDocumentsView.as_view(), name='collection-available-documents'),

    # Collection items (CRUD)
    path('<uuid:collection_id>/items/', CollectionItemListView.as_view(), name='collection-items-list'),
    path('<uuid:collection_id>/items/<uuid:item_id>/', CollectionItemDetailView.as_view(), name='collection-item-detail'),

    # Bulk operations
    path('<uuid:collection_id>/items/reorder/', CollectionItemReorderView.as_view(), name='collection-items-reorder'),
    path('<uuid:collection_id>/items/copy-from/<uuid:source_collection_id>/', CollectionItemCopyFromView.as_view(), name='collection-items-copy-from'),
]
