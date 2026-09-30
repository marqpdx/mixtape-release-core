# dispatch/api/views.py

import base64
import binascii
import hashlib
import hmac
import requests as http_requests
import jwt
from rest_framework import generics
from rest_framework import permissions
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone

# from classifications.api.views import ClassificationUsageListCreateView
# from classifications.models import Category, Tag
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from dispatch.api.serializers import (
    DispatchCommentSerializer,
    DispatchContentSerializer,
    DispatchContentVersionSerializer,
    DispatchEditSessionSerializer,
    DispatchOutlineNodeSerializer,
)
from dispatch.models import (
    DispatchComment,
    DispatchContent,
    DispatchContentVersion,
    DispatchEditSession,
    DispatchOutlineNode,
    Post,
)
from dispatch.access import (
    accessible_dispatch_content,
    can_access_dispatch_content,
    can_access_group_dispatch_piece,
)
from django.contrib.auth import get_user_model
from livewire.auth import ServiceJWTAuthentication
from livewire.permissions import HasDispatchWriteScope
from writing.models import WritingPiece

User = get_user_model()


def _is_dispatch_collaborator(user, piece) -> bool:
    if not user or not user.is_authenticated:
        return False
    return accessible_dispatch_content(user).filter(
        working_documents__piece=piece,
    ).exists()


def _can_view_outline(user, piece) -> bool:
    if not can_access_group_dispatch_piece(user, piece):
        return False
    return piece.author_id == user.id or _is_dispatch_collaborator(user, piece)


def _can_edit_outline(user, piece) -> bool:
    if not can_access_group_dispatch_piece(user, piece):
        return False
    content = DispatchContent.objects.filter(working_documents__piece=piece).first()
    if content:
        return can_access_dispatch_content(user, content, write=True)
    return piece.author_id == user.id


def _build_outline_tree(nodes):
    by_parent = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    def _sorted(items):
        return sorted(items, key=lambda n: (n.order_index, n.created_at))

    def _serialize(node):
        data = DispatchOutlineNodeSerializer(node).data
        data["children"] = [_serialize(child) for child in _sorted(by_parent.get(node.id, []))]
        return data

    roots = _sorted(by_parent.get(None, []))
    return [_serialize(node) for node in roots]


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
            accessible_dispatch_content(user).prefetch_related(
                Prefetch("collaborators", queryset=User.objects.select_related("profile"))
            )
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
        return accessible_dispatch_content(
            self.request.user, write=self.request.method not in permissions.SAFE_METHODS
        )

    def partial_update(self, request, *args, **kwargs):
        """
        Handle hybrid collaborative saves (yjs_state + content_snapshot).
        Includes dedupe and throttle logic to prevent write storms.
        """
        content = self.get_object()

        # Extract save payload
        yjs_state_b64 = request.data.get('yjs_state')
        content_snapshot = request.data.get('body_json') or request.data.get('content_snapshot')
        # external_update=True signals a save from outside the collab editor
        # (e.g. DualPanelEditor). It bypasses the write-storm throttle and
        # clears the Yjs binary state so the next room initialization
        # bootstraps from content_snapshot rather than the stale binary.
        is_external_update = bool(request.data.get('external_update', False))

        # At least one must be provided
        if not yjs_state_b64 and not content_snapshot:
            # Fall back to default serializer behavior for other fields (title, etc.)
            return super().partial_update(request, *args, **kwargs)

        # Dedupe: Check if yjs_state is unchanged
        if yjs_state_b64:
            try:
                new_state_bytes = base64.b64decode(yjs_state_b64)

                # If state is identical to stored state, skip update
                if content.yjs_state and content.yjs_state == new_state_bytes:
                    return Response({
                        "status": "unchanged",
                        "message": "Yjs state unchanged, skipping write"
                    })

            except Exception as e:
                return Response(
                    {"error": f"Failed to decode yjs_state: {str(e)}"},
                    status=400
                )

        # Throttle: Check if last save was too recent.
        # External updates (from DualPanelEditor) bypass this — they are
        # explicit user-initiated saves, not high-frequency autosave beats.
        if not is_external_update and content.yjs_state_updated_at:
            from datetime import timedelta
            time_since_last_save = timezone.now() - content.yjs_state_updated_at

            # Accept max 1 save per 3 seconds (configurable)
            if time_since_last_save < timedelta(seconds=3):
                return Response({
                    "status": "throttled",
                    "message": f"Last save was {time_since_last_save.total_seconds():.1f}s ago, throttling"
                }, status=429)

        # Perform the save
        update_fields = []

        if yjs_state_b64:
            content.yjs_state = new_state_bytes
            content.yjs_state_updated_at = timezone.now()
            update_fields.extend(['yjs_state', 'yjs_state_updated_at'])

        if content_snapshot:
            content.content_snapshot = content_snapshot
            content.snapshot_updated_at = timezone.now()
            update_fields.extend(['content_snapshot', 'snapshot_updated_at'])

        # External update: clear the Yjs binary state so the next livewire room
        # initialization starts empty and bootstraps from content_snapshot.
        # TipTap Collaboration applies initialContent only when the Yjs doc is
        # empty, so this is the mechanism that gets the new content into the editor.
        if is_external_update and not yjs_state_b64:
            content.yjs_state = None
            content.yjs_state_updated_at = None
            if 'yjs_state' not in update_fields:
                update_fields.extend(['yjs_state', 'yjs_state_updated_at'])

        # Update edit tracking
        content.last_edited_by = request.user
        content.last_edited_at = timezone.now()
        update_fields.extend(['last_edited_by', 'last_edited_at'])

        content.save(update_fields=update_fields)

        # Keep the linked WorkingDocument(s) in sync so the writing list and
        # working-copy GET always have current body_json without special-casing.
        if content_snapshot:
            from writing.models import WorkingDocument
            WorkingDocument.objects.filter(dispatch_content=content).update(
                body_json=content_snapshot
            )

        return Response({
            "status": "saved",
            "yjs_state_updated_at": content.yjs_state_updated_at,
            "snapshot_updated_at": content.snapshot_updated_at,
            "last_edited_at": content.last_edited_at,
        })


class DispatchContentYjsStateView(generics.RetrieveUpdateAPIView):
    """
    GET: Retrieve yjs binary state (base64 encoded)
    PATCH: Update yjs binary state from Socket.IO service

    Supports both:
    - Regular JWT authentication (for frontend clients)
    - Service JWT authentication (for livewire Socket.IO server)
    """
    lookup_field = "id"  # UUID lookup
    authentication_classes = [ServiceJWTAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def _signed_livewire_flush(self):
        token = self.request.headers.get("X-Livewire-Persist", "")
        scopes = set((getattr(self.request, "auth_payload", {}) or {}).get("scopes", []))
        if not token or "dispatch:write" not in scopes:
            return None
        try:
            claims = jwt.decode(
                token, settings.LIVEWIRE_JWT_SECRET, algorithms=["HS256"],
                issuer="livewire-persist", audience="django-dispatch",
                options={"require": ["exp", "iat"]},
            )
            state = base64.b64decode(self.request.data.get("yjs_state", ""), validate=True)
            digest = hashlib.sha256(state).hexdigest()
            if not hmac.compare_digest(digest, claims.get("state_sha256", "")):
                return None
            if claims.get("scope") != "dispatch:persist":
                return None
            return claims
        except (jwt.PyJWTError, ValueError, TypeError, binascii.Error):
            return None

    def get_queryset(self):
        if self.request.method == "PATCH":
            claims = self._signed_livewire_flush()
            if claims and str(claims.get("content_id")) == str(self.kwargs["id"]):
                return DispatchContent.objects.filter(
                    pk=self.kwargs["id"], yjs_document_id=claims.get("document_id")
                )
        return accessible_dispatch_content(
            self.request.user, write=self.request.method not in permissions.SAFE_METHODS
        )

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

                # Mirror DispatchContentDetailView: keep linked WorkingDocuments in
                # sync so the writing list and working-copy GET always reflect the
                # latest content without special-casing the collab path.
                if content.content_snapshot:
                    from writing.models import WorkingDocument
                    WorkingDocument.objects.filter(dispatch_content=content).update(
                        body_json=content.content_snapshot
                    )

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


class DispatchRoomAuthorizationView(APIView):
    """Authorize one user-bound Livewire room action against current Core state."""

    authentication_classes = [ServiceJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, HasDispatchWriteScope]

    def post(self, request, id):
        content = get_object_or_404(DispatchContent, pk=id)
        action = request.data.get("action")
        document_id = request.data.get("document_id")
        if action not in {"read", "write"} or not document_id:
            return Response({"detail": "action and document_id are required"}, status=400)
        if str(content.yjs_document_id) != str(document_id):
            return Response({"detail": "Document not found"}, status=404)
        if not can_access_dispatch_content(request.user, content, write=action == "write"):
            return Response({"detail": "Access denied"}, status=403)
        return Response({"allowed": True})


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
        return accessible_dispatch_content(
            self.request.user, write=self.request.method not in permissions.SAFE_METHODS
        )

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


class DispatchContentPresenceView(generics.GenericAPIView):
    """Proxy presence check to Livewire: returns how many clients have this doc open."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        get_object_or_404(accessible_dispatch_content(request.user), pk=id)
        livewire_url = getattr(settings, "LIVEWIRE_INTERNAL_URL", "http://127.0.0.1:5001")
        try:
            resp = http_requests.get(
                f"{livewire_url}/presence",
                params={"contentId": str(id)},
                timeout=2,
            )
            return Response(resp.json())
        except Exception:
            return Response({"active": False, "clients": 0})


# DispatchContentVersion
class DispatchContentVersionListCreateView(generics.ListCreateAPIView):
    serializer_class = DispatchContentVersionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DispatchContentVersion.objects.filter(
            content__in=accessible_dispatch_content(self.request.user)
        )

    def perform_create(self, serializer):
        if not can_access_dispatch_content(self.request.user, serializer.validated_data["content"], write=True):
            raise PermissionDenied
        serializer.save(created_by=self.request.user)


# DispatchEditSession
class DispatchEditSessionListCreateView(generics.ListCreateAPIView):
    serializer_class = DispatchEditSessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DispatchEditSession.objects.filter(
            content__in=accessible_dispatch_content(self.request.user)
        )

    def perform_create(self, serializer):
        if not can_access_dispatch_content(self.request.user, serializer.validated_data["content"], write=True):
            raise PermissionDenied
        serializer.save(user=self.request.user)


class DispatchOutlineListView(generics.GenericAPIView):
    serializer_class = DispatchOutlineNodeSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get(self, request, piece_id=None):
        piece = get_object_or_404(WritingPiece, id=piece_id)
        if not _can_view_outline(request.user, piece):
            return Response(status=403)

        if not piece.enable_outline:
            return Response([])

        nodes = DispatchOutlineNode.objects.filter(
            writing_piece=piece
        ).select_related("parent").order_by("parent_id", "order_index", "created_at")

        return Response(_build_outline_tree(list(nodes)))


class DispatchOutlineCreateView(generics.GenericAPIView):
    serializer_class = DispatchOutlineNodeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        piece = ser.validated_data["writing_piece"]

        if not _can_edit_outline(request.user, piece):
            return Response(status=403)

        if not piece.enable_outline:
            return Response({"detail": "Outline is not enabled for this piece."}, status=400)

        node = ser.save()
        return Response(self.get_serializer(node).data, status=201)


class DispatchOutlineDetailView(generics.GenericAPIView):
    serializer_class = DispatchOutlineNodeSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        return DispatchOutlineNode.objects.all()

    def patch(self, request, id=None):
        node = self.get_object()
        piece = node.writing_piece

        if not _can_edit_outline(request.user, piece):
            return Response(status=403)

        if not piece.enable_outline:
            return Response({"detail": "Outline is not enabled for this piece."}, status=400)

        ser = self.get_serializer(node, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        node = ser.save()
        return Response(self.get_serializer(node).data, status=200)

    def delete(self, request, id=None):
        node = self.get_object()
        piece = node.writing_piece

        if not _can_edit_outline(request.user, piece):
            return Response(status=403)

        node.delete()
        return Response(status=204)


# ── Dispatch Comments ─────────────────────────────────────────────────────────

def _get_dispatch_content_for_piece(piece):
    """Return the DispatchContent linked to this piece, or None."""
    from writing.models import WorkingDocument
    wd = WorkingDocument.objects.filter(piece=piece, dispatch_content__isnull=False).first()
    return wd.dispatch_content if wd else None


def _can_comment_on_piece(user, piece):
    if not user or not user.is_authenticated:
        return False
    if not can_access_group_dispatch_piece(user, piece):
        return False
    if piece.author_id == user.id:
        return True
    dc = _get_dispatch_content_for_piece(piece)
    return dc is not None and can_access_dispatch_content(user, dc)


def _can_resolve_on_piece(user, piece):
    if not user or not user.is_authenticated:
        return False
    if not can_access_group_dispatch_piece(user, piece):
        return False
    if piece.author_id == user.id:
        return True
    dc = _get_dispatch_content_for_piece(piece)
    return dc is not None and can_access_dispatch_content(user, dc, write=True)


class DispatchCommentCreateView(APIView):
    """POST /api/dispatch/comments — create a comment."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        ser = DispatchCommentSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        piece = ser.validated_data["writing_piece"]
        dc = _get_dispatch_content_for_piece(piece)
        if dc is None and piece.author_id != request.user.id:
            raise PermissionDenied("This piece has no collaborative session.")
        if not _can_comment_on_piece(request.user, piece):
            raise PermissionDenied
        comment = ser.save(author=request.user)
        return Response(DispatchCommentSerializer(comment, context={"request": request}).data, status=201)


class DispatchCommentByIdView(APIView):
    """
    GET  /api/dispatch/comments/<id> — list (if id is a WritingPiece) or single comment
    PATCH/DELETE /api/dispatch/comments/<id> — edit/delete a comment by comment id
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, id):
        # Try as WritingPiece first (list endpoint)
        piece = WritingPiece.objects.filter(id=id).first()
        if piece:
            if not _can_comment_on_piece(request.user, piece):
                raise PermissionDenied
            qs = (
                DispatchComment.objects.filter(writing_piece=piece, parent__isnull=True)
                .select_related("author", "resolved_by")
                .prefetch_related("replies__author", "replies__resolved_by")
                .order_by("created_at")
            )
            data = DispatchCommentSerializer(qs, many=True, context={"request": request}).data
            return Response({
                "comments": data,
                "counts": {
                    "total": DispatchComment.objects.filter(writing_piece=piece).count(),
                    "resolved": DispatchComment.objects.filter(
                        writing_piece=piece, resolved_at__isnull=False
                    ).count(),
                },
            })
        # Fall through to single comment
        comment = get_object_or_404(DispatchComment, id=id, deleted_at__isnull=True)
        if not _can_comment_on_piece(request.user, comment.writing_piece):
            raise PermissionDenied
        return Response(DispatchCommentSerializer(comment, context={"request": request}).data)

    def patch(self, request, id):
        comment = get_object_or_404(DispatchComment, id=id, deleted_at__isnull=True)
        if comment.author_id != request.user.id or not _can_comment_on_piece(request.user, comment.writing_piece):
            raise PermissionDenied("Only the comment author can edit.")
        body = request.data.get("body", "").strip()
        if not body:
            return Response({"body": "Required."}, status=400)
        comment.body = body
        comment.save(update_fields=["body", "updated_at"])
        return Response(DispatchCommentSerializer(comment, context={"request": request}).data)

    def delete(self, request, id):
        comment = get_object_or_404(DispatchComment, id=id, deleted_at__isnull=True)
        is_author = comment.author_id == request.user.id and _can_comment_on_piece(request.user, comment.writing_piece)
        is_editor = _can_resolve_on_piece(request.user, comment.writing_piece)
        if not (is_author or is_editor):
            raise PermissionDenied
        comment.delete()
        return Response(status=204)


class DispatchCommentResolveView(APIView):
    """POST /api/dispatch/comments/<id>/resolve — editors only."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        comment = get_object_or_404(DispatchComment, id=id, deleted_at__isnull=True)
        if not _can_resolve_on_piece(request.user, comment.writing_piece):
            raise PermissionDenied("Only editors can resolve comments.")
        comment.resolved_at = timezone.now()
        comment.resolved_by = request.user
        comment.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
        return Response(DispatchCommentSerializer(comment, context={"request": request}).data)


class DispatchCommentUnresolveView(APIView):
    """POST /api/dispatch/comments/<id>/unresolve — editors only."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, id):
        comment = get_object_or_404(DispatchComment, id=id, deleted_at__isnull=True)
        if not _can_resolve_on_piece(request.user, comment.writing_piece):
            raise PermissionDenied("Only editors can unresolve comments.")
        comment.resolved_at = None
        comment.resolved_by = None
        comment.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
        return Response(DispatchCommentSerializer(comment, context={"request": request}).data)
