# curation/urls.py

from django.urls import path

from .api.views import (
    CollectionListView,
    CollectionDetailView,
    CollectionAvailableFilesView,
    CollectionAvailableDocumentsView,
    CollectionUploadView,
    CollectionItemListView,
    CollectionItemDetailView,
    CollectionItemReorderView,
    CollectionItemCopyFromView,
)

urlpatterns = [
    # Collection list / create
    path('', CollectionListView.as_view(), name='collection-list'),

    # Collection detail / update / delete
    path('<uuid:collection_id>/', CollectionDetailView.as_view(), name='collection-detail'),

    # Available files (SourceFiles in the sponsor's Stackroom library)
    path('<uuid:collection_id>/available-files/', CollectionAvailableFilesView.as_view(), name='collection-available-files'),

    # Upload a new file into the sponsor's Stackroom library
    path('<uuid:collection_id>/upload', CollectionUploadView.as_view(), name='collection-upload'),

    # Available documents (WritingPieces eligible to add)
    path('<uuid:collection_id>/available-documents/', CollectionAvailableDocumentsView.as_view(), name='collection-available-documents'),

    # Collection items (CRUD)
    path('<uuid:collection_id>/items/', CollectionItemListView.as_view(), name='collection-items-list'),
    path('<uuid:collection_id>/items/<int:item_id>/', CollectionItemDetailView.as_view(), name='collection-item-detail'),

    # Bulk operations
    path('<uuid:collection_id>/items/reorder/', CollectionItemReorderView.as_view(), name='collection-items-reorder'),
    path('<uuid:collection_id>/items/copy-from/<uuid:source_collection_id>/', CollectionItemCopyFromView.as_view(), name='collection-items-copy-from'),
]
