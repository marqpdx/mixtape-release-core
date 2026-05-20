from django.urls import path

from . import views

urlpatterns = [
    path('personal', views.PersonalPuddlejumpView.as_view(), name='puddlejump-personal'),
    path('sync/status', views.SyncStatusView.as_view(), name='puddlejump-sync-status'),
    path('sync/upload', views.SyncUploadView.as_view(), name='puddlejump-sync-upload'),
    path('sync/download/<uuid:item_id>/', views.SyncDownloadView.as_view(), name='puddlejump-sync-download'),
    path('sync/delete/<uuid:item_id>/', views.SyncDeleteView.as_view(), name='puddlejump-sync-delete'),
    path('sync/complete', views.SyncCompleteView.as_view(), name='puddlejump-sync-complete'),
    path('<slug:group_slug>/', views.GroupPuddlejumpView.as_view(), name='puddlejump-group'),
]
