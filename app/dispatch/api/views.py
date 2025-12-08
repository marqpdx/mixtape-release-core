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
from dispatch.api.serializers import DispatchContentSerializer, DispatchContentVersionSerializer, DispatchEditSessionSerializer
from dispatch.models import DispatchContent, DispatchContentVersion, DispatchEditSession, Post
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




# DispatchContent (Collaborative Editing Infrastructure)
class DispatchContentListCreateView(generics.ListCreateAPIView):
    """
    List/Create collaborative editing sessions.
    Note: DispatchContent is infrastructure only - no sponsor/author fields.
    """
    serializer_class = DispatchContentSerializer
    pagination_class = None

    def get_queryset(self):
        user = self.request.user

        # Base queryset: content where user is a collaborator
        qs = (
            DispatchContent.objects.prefetch_related(
                Prefetch("collaborators", queryset=User.objects.select_related("profile"))
            )
            .filter(collaborators=user)
        )

        return qs

    def perform_create(self, serializer):
        # Create content and add creator as collaborator
        content = serializer.save()
        content.collaborators.add(self.request.user)


class DispatchContentDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = DispatchContentSerializer
    lookup_field = "id"  # UUID lookup

    def get_queryset(self):
        user = self.request.user
        return DispatchContent.objects.filter(collaborators=user)


class DispatchContentYjsStateView(generics.RetrieveUpdateAPIView):
    """
    GET: Retrieve yjs binary state (base64 encoded)
    PATCH: Update yjs binary state from Socket.IO service
    """
    lookup_field = "id"  # UUID lookup
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return DispatchContent.objects.none()
        return DispatchContent.objects.filter(collaborators=user)

    def retrieve(self, request, *args, **kwargs):
        content = self.get_object()

        # Return base64-encoded yjs state
        yjs_state_b64 = None
        if content.yjs_state:
            yjs_state_b64 = base64.b64encode(content.yjs_state).decode('utf-8')

        return Response({
            "yjs_state": yjs_state_b64,
            "yjs_state_updated_at": content.yjs_state_updated_at,
        })

    def partial_update(self, request, *args, **kwargs):
        content = self.get_object()

        # Decode base64 yjs state and save
        yjs_state_b64 = request.data.get('yjs_state')
        if yjs_state_b64:
            try:
                content.yjs_state = base64.b64decode(yjs_state_b64)
                content.yjs_state_updated_at = timezone.now()
                content.save(update_fields=['yjs_state', 'yjs_state_updated_at'])

                return Response({
                    "status": "updated",
                    "yjs_state_updated_at": content.yjs_state_updated_at,
                })
            except Exception as e:
                return Response(
                    {"error": f"Failed to decode yjs_state: {str(e)}"},
                    status=400
                )

        return Response({"error": "No yjs_state provided"}, status=400)


class DispatchContentCollaboratorsView(generics.GenericAPIView):
    """
    Manage collaborators for dispatch content.
    GET: List current collaborators
    POST: Add collaborators (expects {"user_ids": [...]})
    DELETE: Remove collaborators (expects {"user_ids": [...]})

    Note: This is infrastructure-level collaboration management.
    Context-specific permission checks (e.g., group membership) should
    happen at the WorkingDocument/WorkingCourse level.
    """
    lookup_field = "id"  # UUID lookup
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return DispatchContent.objects.filter(collaborators=user)

    def get(self, request, *args, **kwargs):
        """List current collaborators"""
        content = self.get_object()

        from accounts.api.serializers import UserSerializer
        collaborators = UserSerializer(content.collaborators.all(), many=True).data

        return Response({
            "collaborators": collaborators,
        })

    def post(self, request, *args, **kwargs):
        """Add collaborators to content with specified role"""
        from dispatch.models import DispatchCollaborator

        content = self.get_object()
        user_ids = request.data.get('user_ids', [])
        role = request.data.get('role', 'editor')  # Default to editor

        if not user_ids:
            return Response({"error": "user_ids required"}, status=400)

        # Validate role
        if role not in ['editor', 'commenter']:
            return Response({"error": "role must be 'editor' or 'commenter'"}, status=400)

        # Verify users exist
        users = User.objects.filter(id__in=user_ids)

        if users.count() != len(user_ids):
            return Response({"error": "Some user IDs are invalid"}, status=400)

        # Add collaborators with role
        added_collaborators = []
        for user in users:
            collaborator, created = DispatchCollaborator.objects.get_or_create(
                content=content,
                user=user,
                defaults={
                    'role': role,
                    'invited_by': request.user
                }
            )
            if not created and collaborator.role != role:
                # Update role if different
                collaborator.role = role
                collaborator.save()
            added_collaborators.append(collaborator)

        from dispatch.api.serializers import DispatchCollaboratorSerializer
        return Response({
            "collaborators": DispatchCollaboratorSerializer(
                content.collaborator_assignments.all(),
                many=True
            ).data
        })

    def delete(self, request, *args, **kwargs):
        """Remove collaborators from content"""
        content = self.get_object()
        user_ids = request.data.get('user_ids', [])

        if not user_ids:
            return Response({"error": "user_ids required"}, status=400)

        users = User.objects.filter(id__in=user_ids)

        # Remove collaborators
        content.collaborators.remove(*users)

        from accounts.api.serializers import UserSerializer
        return Response({
            "collaborators": UserSerializer(content.collaborators.all(), many=True).data
        })


# DispatchContentVersion
class DispatchContentVersionListCreateView(generics.ListCreateAPIView):
    queryset = DispatchContentVersion.objects.all()
    serializer_class = DispatchContentVersionSerializer


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