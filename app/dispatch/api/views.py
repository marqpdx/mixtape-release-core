# dispatch/api/views.py

import base64
from rest_framework import generics
from rest_framework import permissions
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db.models import Prefetch
from django.utils import timezone

# from classifications.api.views import ClassificationUsageListCreateView
# from classifications.models import Category, Tag
from dispatch.api.serializers import DispatchDocumentSerializer, DispatchDocumentVersionSerializer, DispatchEditSessionSerializer
from dispatch.models import DispatchDocument, DispatchDocumentVersion, DispatchEditSession, Post
from django.contrib.auth import get_user_model

User = get_user_model()


# class PostListCreateView(generics.ListCreateAPIView):
#     queryset = Post.objects.all().order_by("-created_at")
#     serializer_class = PostSerializer
#     permission_classes = [permissions.IsAuthenticated]

#     def perform_create(self, serializer):
#         serializer.save()


# class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
#     queryset = Post.objects.all()
#     serializer_class = PostSerializer
#     permission_classes = [permissions.IsAuthenticated]
#     lookup_field = "slug"  # or "pk" if preferred


# class PostTagListCreateView(ClassificationUsageListCreateView):
#     model_class = Post
#     classification_model = Tag


# class PostCategoryListCreateView(ClassificationUsageListCreateView):
#     model_class = Post
#     classification_model = Category




# DispatchDocument
class DispatchDocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = DispatchDocumentSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user
        group_slug = self.request.query_params.get('group_slug')

        # Base queryset: documents where user is a collaborator
        qs = (
            DispatchDocument.objects.prefetch_related(
                Prefetch("collaborators", queryset=User.objects.select_related("profile"))
            )
            .filter(collaborators=user)
        )

        # Filter by group sponsor if group_slug provided
        if group_slug:
            from groups.models import Group
            from django.contrib.contenttypes.models import ContentType

            try:
                group = Group.objects.get(slug=group_slug)
                group_ct = ContentType.objects.get_for_model(Group)
                qs = qs.filter(
                    sponsor_content_type=group_ct,
                    sponsor_object_id=group.id
                )
            except Group.DoesNotExist:
                # Return empty queryset if group doesn't exist
                return DispatchDocument.objects.none()

        return qs

    def perform_create(self, serializer):
        # Get sponsor from request data
        sponsor_type = self.request.data.get('sponsor_type')
        sponsor_id = self.request.data.get('sponsor_id')

        # Create document with submitted_by (replaces old created_by)
        document = serializer.save(
            submitted_by=self.request.user,
            author=self.request.user
        )

        # Add creator as collaborator
        document.collaborators.add(self.request.user)

        # Set sponsor if provided
        if sponsor_type == 'group' and sponsor_id:
            from groups.models import Group
            try:
                group = Group.objects.get(id=sponsor_id)
                document.set_sponsor(group)
                document.save(update_fields=['sponsor_content_type', 'sponsor_object_id'])
            except Group.DoesNotExist:
                pass  # Sponsor not set if group doesn't exist


class DispatchDocumentDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = DispatchDocumentSerializer
    lookup_field = "slug"

    def get_queryset(self):
        print(f"[DEBUG] Current request: {self.request.data}")
        user = self.request.user
        return DispatchDocument.objects.filter(collaborators=user)


class DispatchDocumentYjsStateView(generics.RetrieveUpdateAPIView):
    """
    GET: Retrieve yjs binary state (base64 encoded)
    PATCH: Update yjs binary state from Socket.IO service
    """
    lookup_field = "slug"
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return DispatchDocument.objects.none()
        return DispatchDocument.objects.filter(collaborators=user)

    def retrieve(self, request, *args, **kwargs):
        document = self.get_object()

        # Return base64-encoded yjs state
        yjs_state_b64 = None
        if document.yjs_state:
            yjs_state_b64 = base64.b64encode(document.yjs_state).decode('utf-8')

        return Response({
            "yjs_state": yjs_state_b64,
            "yjs_state_updated_at": document.yjs_state_updated_at,
        })

    def partial_update(self, request, *args, **kwargs):
        document = self.get_object()

        # Decode base64 yjs state and save
        yjs_state_b64 = request.data.get('yjs_state')
        if yjs_state_b64:
            try:
                document.yjs_state = base64.b64decode(yjs_state_b64)
                document.yjs_state_updated_at = timezone.now()
                document.save(update_fields=['yjs_state', 'yjs_state_updated_at'])

                return Response({
                    "status": "updated",
                    "yjs_state_updated_at": document.yjs_state_updated_at,
                })
            except Exception as e:
                return Response(
                    {"error": f"Failed to decode yjs_state: {str(e)}"},
                    status=400
                )

        return Response({"error": "No yjs_state provided"}, status=400)


class DispatchDocumentCollaboratorsView(generics.GenericAPIView):
    """
    Manage collaborators for a dispatch document
    GET: List current collaborators
    POST: Add collaborators (expects {"user_ids": [...]})
    DELETE: Remove collaborators (expects {"user_ids": [...]})
    """
    lookup_field = "slug"
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return DispatchDocument.objects.filter(collaborators=user)

    def get(self, request, *args, **kwargs):
        """List current collaborators"""
        document = self.get_object()

        # Get group members if document has group sponsor
        available_users = []
        if document.sponsor and hasattr(document.sponsor, 'members'):
            # Document is sponsored by a group - only show group members
            from accounts.api.serializers import UserSerializer
            available_users = UserSerializer(
                document.sponsor.members.all(),
                many=True
            ).data

        from accounts.api.serializers import UserSerializer
        collaborators = UserSerializer(document.collaborators.all(), many=True).data

        return Response({
            "collaborators": collaborators,
            "available_users": available_users,
        })

    def post(self, request, *args, **kwargs):
        """Add collaborators to document"""
        document = self.get_object()
        user_ids = request.data.get('user_ids', [])

        if not user_ids:
            return Response({"error": "user_ids required"}, status=400)

        # Verify users exist and are in the group (if group-sponsored)
        users = User.objects.filter(id__in=user_ids)

        if document.sponsor and hasattr(document.sponsor, 'members'):
            # Verify all users are group members
            group_member_ids = set(document.sponsor.members.values_list('id', flat=True))
            for user in users:
                if user.id not in group_member_ids:
                    return Response(
                        {"error": f"User {user.username} is not a member of this group"},
                        status=403
                    )

        # Add collaborators
        document.collaborators.add(*users)

        from accounts.api.serializers import UserSerializer
        return Response({
            "collaborators": UserSerializer(document.collaborators.all(), many=True).data
        })

    def delete(self, request, *args, **kwargs):
        """Remove collaborators from document"""
        document = self.get_object()
        user_ids = request.data.get('user_ids', [])

        if not user_ids:
            return Response({"error": "user_ids required"}, status=400)

        users = User.objects.filter(id__in=user_ids)

        # Don't allow removing the document creator
        if document.submitted_by and document.submitted_by.id in user_ids:
            return Response(
                {"error": "Cannot remove document creator"},
                status=403
            )

        # Remove collaborators
        document.collaborators.remove(*users)

        from accounts.api.serializers import UserSerializer
        return Response({
            "collaborators": UserSerializer(document.collaborators.all(), many=True).data
        })


# DispatchDocumentVersion
class DispatchDocumentVersionListCreateView(generics.ListCreateAPIView):
    queryset = DispatchDocumentVersion.objects.all()
    serializer_class = DispatchDocumentVersionSerializer


# DispatchEditSession
class DispatchEditSessionListCreateView(generics.ListCreateAPIView):
    queryset = DispatchEditSession.objects.all()
    serializer_class = DispatchEditSessionSerializer









# old style
# class DispatchDocumentViewSet(viewsets.ModelViewSet):
#     queryset = DispatchDocument.objects.all()
#     serializer_class = DispatchDocumentSerializer
#     lookup_field = "slug"
#     pagination_class = None

#     def get_queryset(self):
#         user = self.request.user
#         return (
#             DispatchDocument.objects.prefetch_related(
#                 Prefetch("collaborators", queryset=User.objects.select_related("profile"))
#             )
#             .filter(collaborators=user)
#         )

#     def perform_create(self, serializer):
#         document = serializer.save(created_by=self.request.user)
#         document.collaborators.add(self.request.user)


# class DispatchDocumentVersionViewSet(viewsets.ModelViewSet):
#     queryset = DispatchDocumentVersion.objects.all()
#     serializer_class = DispatchDocumentVersionSerializer


# class DispatchEditSessionViewSet(viewsets.ModelViewSet):
#     queryset = DispatchEditSession.objects.all()
#     serializer_class = DispatchEditSessionSerializer