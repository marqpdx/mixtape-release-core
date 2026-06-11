# groups/api/urls.py

from django.urls import include, path

# ============================================================================
# PHASE 2: Active Views
# ============================================================================
from .views import (
    GroupCircleDetailView,
    GroupCirclesListCreateView,
    GroupCoalitionInvitationsListView,
    GroupCoalitionInvitationsReceivedListView,
    GroupContextView,
    DefaultGroupView,
    GroupDetailView,
    GroupEmblemAttachView,
    GroupEmblemResetView,
    GroupOverviewLayoutView,
    GroupInvitationDetailView,
    GroupInvitationsListView,
    GroupListCreateView,
    GroupMemberRemoveView,
    GroupMemberSearchView,
    GroupMembersView,
    GroupWelcomePinView,
    UserGroupsView,
    invite_to_group,
    GroupJoinRequestsListView,
    invite_group_to_coalition,
    join_group,
    request_to_join_coalition,
    request_to_join_group,
    respond_to_group_invitation,
    respond_to_join_request,
)

from .permissions_views import (
    AvailablePermissionsView,
    GroupPermissionProfileCloneView,
    GroupPermissionProfileDetailView,
    GroupPermissionProfileListView,
    GroupPermissionProfileSetDefaultView,
    MemberPermissionsListView,
    MemberPermissionProfileManageView,
    MemberPermissionManageView,
    MemberHelperManageView,
    MemberRoleManageView,
    MyPermissionsView,
)
from .ownership_views import (
    OwnershipRequestCreateView,
    OwnershipRequestListView,
    OwnershipRequestCancelView,
)
from .files_views import (
    GroupFilesListView,
    GroupFileUploadView,
    GroupFileDeleteView,
    GroupFileDownloadView,
    GroupFilePreviewView,
)
from writing.api.views import WritingPieceDetailView


# ============================================================================
# PHASE 3+: Deferred App Integrations
# ============================================================================
# from assets.api.views import GroupAssetFolderListView, GroupAssetListView, GroupAssetPresignView, GroupAssetUploadView
# from writing.api.views import WritingPieceDetailView
from .views import GroupAnnouncementCreateFromContentView, GroupAnnouncementDetailView, GroupAnnouncementDismissView, GroupAnnouncementListCreateView, GroupAnnouncementVisibleQueueView
# from .views import GroupInvitationDetailView, GroupInvitationsListView, GroupMemberSearchView, GroupMembersListView, GroupMembersView, GroupMembershipListView, GroupNoticeBoardView, invite_to_group
# from .views import GroupEmblemAttachView, GroupEmblemResetView, GroupWritingDetailView, GroupWritingDraftsListView, GroupWritingListCreateView  # PHASE 3+
from threadworks.api.urls import group_threadworks_patterns
from almanac.api.urls import group_almanac_patterns
from lanternmail.api.urls import group_lanternmail_patterns
from initiatives.api.urls import group_initiatives_patterns
from workbench.api.urls import group_workbench_patterns
# from earthlab.api.urls import group_course_patterns

# base path: api/groups/

urlpatterns = [

    # ============================================================================
    # Group File Library (Stackroom)
    # ============================================================================
    path('<slug:slug>/files/', GroupFilesListView.as_view(), name='group-files-list'),
    path('<slug:slug>/files/upload/', GroupFileUploadView.as_view(), name='group-files-upload'),
    path('<slug:slug>/files/<uuid:source_file_id>/', GroupFileDeleteView.as_view(), name='group-file-delete'),
    path('<slug:slug>/files/<uuid:source_file_id>/download/', GroupFileDownloadView.as_view(), name='group-file-download'),
    path('<slug:slug>/files/<uuid:source_file_id>/preview.pdf', GroupFilePreviewView.as_view(), name='group-file-preview'),

    # ============================================================================
    # PHASE 3+: Deferred App URL Patterns
    # ============================================================================
    path('<slug:slug>/threadworks/', include(group_threadworks_patterns)),
    path('<slug:slug>/almanac/', include(group_almanac_patterns)),
    path('<slug:slug>/lanternmail/', include(group_lanternmail_patterns)),
    path('<slug:slug>/initiatives/', include(group_initiatives_patterns)),  # /api/groups/<slug>/initiatives/...
    path('<slug:slug>/workbench/', include(group_workbench_patterns)),      # /api/groups/<slug>/workbench/...
    # path('/<slug:group_slug>/earthlab', include(group_course_patterns)),

    path("", GroupListCreateView.as_view(), name="group-list-create"),
    path("my", UserGroupsView.as_view(), name="user-groups"),  # /api/groups/my
    path("default", DefaultGroupView.as_view(), name="default-group"),
    path("<slug:slug>", GroupDetailView.as_view(), name="group-detail"),  # /api/groups/<slug>/
    path("<slug:group_slug>/writing/<slug:piece_slug>", WritingPieceDetailView.as_view(), name="writingpiece-detail"),
    path("<slug:slug>/welcome", GroupWelcomePinView.as_view(), name="group-welcome-pin"),
    path("<slug:slug>/emblem/attach", GroupEmblemAttachView.as_view(), name="group-emblem-attach"),
    path("<slug:slug>/emblem/reset", GroupEmblemResetView.as_view(), name="group-emblem-reset"),
    path("<slug:slug>/overview-layout", GroupOverviewLayoutView.as_view(), name="group-overview-layout"),
    path("<slug:slug>/context", GroupContextView.as_view(), name="group-context"),

    # Group membership - consolidated single endpoint
    path("<slug:slug>/members", GroupMembersView.as_view(), name="group-members"),
    path("<slug:slug>/members/search", GroupMemberSearchView.as_view(), name="group-member-search"),
    path("<slug:slug>/members/<uuid:membership_id>", GroupMemberRemoveView.as_view(), name="group-member-remove"),

    path("<slug:slug>/circles", GroupCirclesListCreateView.as_view(), name="group-circles-list-create"),
    path("<slug:parent_slug>/circles/<slug:circle_slug>", GroupCircleDetailView.as_view(), name="group-circle-detail"),

    # Permissions management
    path("<slug:slug>/permissions/available", AvailablePermissionsView.as_view(), name="group-permissions-available"),
    path("<slug:slug>/permission-profiles", GroupPermissionProfileListView.as_view(), name="group-permission-profile-list"),
    path("<slug:slug>/permission-profiles/<int:profile_id>", GroupPermissionProfileDetailView.as_view(), name="group-permission-profile-detail"),
    path("<slug:slug>/permission-profiles/<int:profile_id>/clone", GroupPermissionProfileCloneView.as_view(), name="group-permission-profile-clone"),
    path("<slug:slug>/permission-profiles/<int:profile_id>/set-default", GroupPermissionProfileSetDefaultView.as_view(), name="group-permission-profile-set-default"),
    path("<slug:slug>/members/permissions", MemberPermissionsListView.as_view(), name="group-member-permissions-list"),
    path("<slug:slug>/members/<uuid:user_id>/permission-profile", MemberPermissionProfileManageView.as_view(), name="group-member-permission-profile"),
    path("<slug:slug>/members/<uuid:user_id>/permissions", MemberPermissionManageView.as_view(), name="group-member-permission-grant"),
    path("<slug:slug>/members/<uuid:user_id>/permissions/<str:decorator>", MemberPermissionManageView.as_view(), name="group-member-permission-revoke"),
    path("<slug:slug>/members/<uuid:user_id>/roles", MemberRoleManageView.as_view(), name="group-member-role-grant"),
    path("<slug:slug>/members/<uuid:user_id>/helper", MemberHelperManageView.as_view(), name="group-member-helper-manage"),
    path("<slug:slug>/my-permissions", MyPermissionsView.as_view(), name="group-my-permissions"),

#     # Invitations
    path("<slug:slug>/invite", invite_to_group, name="group-invite"),
    path("<slug:slug>/invitations", GroupInvitationsListView.as_view(), name="group-invitations"),
    path("<slug:group_slug>/invitations/<int:pk>", GroupInvitationDetailView.as_view(), name="group-invitation-detail", ),

    # User join / request-to-join
    path("<slug:slug>/join", join_group, name="group-join"),
    path("<slug:slug>/request-join", request_to_join_group, name="group-request-join"),
    path("<slug:slug>/join-requests", GroupJoinRequestsListView.as_view(), name="group-join-requests"),
    path("<slug:slug>/join-requests/<int:invitation_id>/respond", respond_to_join_request, name="group-join-request-respond"),

    # Coalition invitations / requests
    path("<slug:slug>/coalition-invitations", GroupCoalitionInvitationsListView.as_view(), name="group-coalition-invitations"),
    path("<slug:slug>/coalition-invitations/received", GroupCoalitionInvitationsReceivedListView.as_view(), name="group-coalition-invitations-received"),
    path("<slug:slug>/coalition-invitations/invite", invite_group_to_coalition, name="group-coalition-invite"),
    path("<slug:slug>/coalition-invitations/request", request_to_join_coalition, name="group-coalition-request"),
    path("coalition-invitations/<int:invitation_id>/respond", respond_to_group_invitation, name="group-coalition-respond"),

    # Ownership change requests
    path("<slug:slug>/ownership/requests", OwnershipRequestListView.as_view(), name="group-ownership-requests"),
    path("<slug:slug>/ownership/requests/create", OwnershipRequestCreateView.as_view(), name="group-ownership-request-create"),
    path("<slug:slug>/ownership/requests/<uuid:request_id>/cancel", OwnershipRequestCancelView.as_view(), name="group-ownership-request-cancel"),

    # ============================================================================
    # PHASE 3: Emblems (Enabled)
    # ============================================================================


    # Group Announcements
    path('<slug:group_slug>/announcements/', GroupAnnouncementListCreateView.as_view(), name='group-announcements-list'),
    path('<slug:group_slug>/announcements/visible-queue/', GroupAnnouncementVisibleQueueView.as_view(), name='group-announcements-visible-queue'),
    path('<slug:group_slug>/announcements/create-from-content/', GroupAnnouncementCreateFromContentView.as_view(), name='group-announcements-create-from-content'),
    path('<slug:group_slug>/announcements/<uuid:pk>/', GroupAnnouncementDetailView.as_view(), name='group-announcements-detail'),
    path('<slug:group_slug>/announcements/<uuid:pk>/dismiss/', GroupAnnouncementDismissView.as_view(), name='group-announcements-dismiss'),

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
