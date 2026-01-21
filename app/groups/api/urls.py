# groups/api/urls.py

from django.urls import include, path

# ============================================================================
# PHASE 2: Active Views
# ============================================================================
from .views import (
    GroupCirclesListCreateView,
    GroupCoalitionInvitationsListView,
    GroupCoalitionInvitationsReceivedListView,
    GroupDetailView,
    GroupInvitationDetailView,
    GroupInvitationsListView,
    GroupListCreateView,
    GroupMemberSearchView,
    GroupMembersView,
    UserGroupsView,
    invite_to_group,
    invite_group_to_coalition,
    request_to_join_coalition,
    respond_to_group_invitation,
)

from .permissions_views import (
    AvailablePermissionsView,
    MemberPermissionsListView,
    MemberPermissionManageView,
    MyPermissionsView,
)


# ============================================================================
# PHASE 3+: Deferred App Integrations
# ============================================================================
# from assets.api.views import GroupAssetFolderListView, GroupAssetListView, GroupAssetPresignView, GroupAssetUploadView
# from writing.api.views import WritingPieceDetailView
# from .views import GroupAnnouncementCreateFromContentView, GroupAnnouncementDetailView, GroupAnnouncementDismissView, GroupAnnouncementListCreateView, GroupAnnouncementVisibleQueueView, GroupInvitationDetailView, GroupInvitationsListView, GroupMemberSearchView, GroupMembersListView, GroupMembersView, GroupMembershipListView, GroupNoticeBoardView, invite_to_group
# from .views import GroupEmblemAttachView, GroupEmblemResetView, GroupWritingDetailView, GroupWritingDraftsListView, GroupWritingListCreateView  # PHASE 3+
from threadworks.api.urls import group_threadworks_patterns
from almanac.api.urls import group_almanac_patterns
from lanternmail.api.urls import group_lanternmail_patterns
# from earthlab.api.urls import group_course_patterns

# base path: api/groups/

urlpatterns = [

    # ============================================================================
    # PHASE 3+: Deferred App URL Patterns
    # ============================================================================
    path('<slug:slug>/threadworks/', include(group_threadworks_patterns)),
    path('<slug:slug>/almanac/', include(group_almanac_patterns)),  # /api/groups/<slug>/almanac/...
    path('<slug:slug>/lanternmail/', include(group_lanternmail_patterns)),  # /api/groups/<slug>/lanternmail/...
    # path('/<slug:group_slug>/earthlab', include(group_course_patterns)),

    path("", GroupListCreateView.as_view(), name="group-list-create"),
    path("my", UserGroupsView.as_view(), name="user-groups"),  # /api/groups/my
    path("<slug:slug>", GroupDetailView.as_view(), name="group-detail"),  # /api/groups/<slug>/

    # Group membership - consolidated single endpoint
    path("<slug:slug>/members", GroupMembersView.as_view(), name="group-members"),
    path("<slug:slug>/members/search", GroupMemberSearchView.as_view(), name="group-member-search"),

    path("<slug:slug>/circles", GroupCirclesListCreateView.as_view(), name="group-circles-list-create"),

    # Permissions management
    path("<slug:slug>/permissions/available", AvailablePermissionsView.as_view(), name="group-permissions-available"),
    path("<slug:slug>/members/permissions", MemberPermissionsListView.as_view(), name="group-member-permissions-list"),
    path("<slug:slug>/members/<uuid:user_id>/permissions", MemberPermissionManageView.as_view(), name="group-member-permission-grant"),
    path("<slug:slug>/members/<uuid:user_id>/permissions/<str:decorator>", MemberPermissionManageView.as_view(), name="group-member-permission-revoke"),
    path("<slug:slug>/my-permissions", MyPermissionsView.as_view(), name="group-my-permissions"),

#     # Invitations
    path("<slug:slug>/invite", invite_to_group, name="group-invite"),
    path("<slug:slug>/invitations", GroupInvitationsListView.as_view(), name="group-invitations"),
    path("<slug:group_slug>/invitations/<int:pk>", GroupInvitationDetailView.as_view(), name="group-invitation-detail", ),

    # Coalition invitations / requests
    path("<slug:slug>/coalition-invitations", GroupCoalitionInvitationsListView.as_view(), name="group-coalition-invitations"),
    path("<slug:slug>/coalition-invitations/received", GroupCoalitionInvitationsReceivedListView.as_view(), name="group-coalition-invitations-received"),
    path("<slug:slug>/coalition-invitations/invite", invite_group_to_coalition, name="group-coalition-invite"),
    path("<slug:slug>/coalition-invitations/request", request_to_join_coalition, name="group-coalition-request"),
    path("coalition-invitations/<int:invitation_id>/respond", respond_to_group_invitation, name="group-coalition-respond"),

    # ============================================================================
    # PHASE 3: Emblems (Deferred - requires identity app)
    # ============================================================================
    # path('/<slug:group_slug>/emblem/attach', GroupEmblemAttachView.as_view(), name='group-emblem-attach'),
    # path('/<slug:group_slug>/emblem/reset', GroupEmblemResetView.as_view(), name='group-emblem-reset'),


    # Group Announcements
#     path('groups/<slug:group_slug>/announcements/',
#          GroupAnnouncementListCreateView.as_view(),
#          name='group-announcements-list'),

#     path('groups/<slug:group_slug>/announcements/<uuid:pk>/',
#          GroupAnnouncementDetailView.as_view(),
#          name='group-announcements-detail'),

#     path('groups/<slug:group_slug>/announcements/visible-queue/',
#          GroupAnnouncementVisibleQueueView.as_view(),
#          name='group-announcements-visible-queue'),

#     path('groups/<slug:group_slug>/announcements/<uuid:pk>/dismiss/',
#          GroupAnnouncementDismissView.as_view(),
#          name='group-announcements-dismiss'),

#     path('groups/<slug:group_slug>/announcements/create-from-content/',
#          GroupAnnouncementCreateFromContentView.as_view(),
#          name='group-announcements-create-from-content'),

#     path("/<slug:slug>/memberships", GroupMembershipListView.as_view(), name="group-memberships"),

#     # ============================================================================
#     # PHASE 3+: Writing & Assets (Deferred)
#     # ============================================================================
#     # Move these to writing/api/urls.py later?
#     # path("/<slug:slug>/writing", GroupWritingListCreateView.as_view(), name="group-posts-list"),
#     # path("/<slug:slug>/writing/drafts", GroupWritingDraftsListView.as_view(), name="group-writing-drafts-list"),
#     # path("/<slug:slug>/writing/<slug:piece_slug>", GroupWritingDetailView.as_view(), name="group-posts-detail"),
#     # path("/<slug:group_slug>/writing/<slug:piece_slug>", WritingPieceDetailView.as_view(), name='writingpiece-detail'),

#     path("/<slug:slug>/noticeboard", GroupNoticeBoardView.as_view(), name="group-noticeboard"),

#     path("/<slug:group_slug>/invitations/<int:pk>", GroupInvitationDetailView.as_view(), name="group-invitation-detail", ),

    # ============================================================================
    # PHASE 3: Assets (Deferred - requires assets app)
    # ============================================================================
    # path("/<uuid:group_id>/assets/upload", GroupAssetUploadView.as_view(), name="group-asset-upload", ),
    # path("/<uuid:group_id>/assets", GroupAssetListView.as_view(), name="group-asset-list", ),
    # path("/group-asset/<int:group_asset_id>/presign", GroupAssetPresignView.as_view(), name="group-asset-presign", ),
    # path("/<uuid:group_id>/assets/folders", GroupAssetFolderListView.as_view(), name="group-asset-folders",),

]

