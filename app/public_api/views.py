# public_api/views.py

"""
Public API views for anonymous + logged-in reader surface.

All endpoints use AllowAny permissions with server-side visibility enforcement.
No email, roles, or internal data exposed.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status as drf_status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from profiles.models import UserProfile
from publishing.models import ContentPlacement
from publishing.services.content_access import can_view_placement
from publishing.services.content_display import get_display_payload
from curation.models import Collection
from writing.models import WritingPiece
from earthlab.models import Course, CourseItem

from django.db.models import Count, Q

from groups.models.group import Group
from groups.services.join_service import get_admission_status

from .serializers import (
    PublicGroupDetailSerializer,
    PublicGroupSerializer,
    PublicMemberSerializer,
)


class PublicGroupsListView(APIView):
    """
    GET /api/public/groups

    Returns all public, active groups with emblem data and member counts.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        groups = (
            Group.objects.filter(
                visibility="public",
                is_active=True,
            )
            .select_related("emblem", "sponsor_content_type")
            .annotate(
                member_count=Count(
                    "memberships",
                    filter=Q(
                        memberships__is_active=True,
                        memberships__is_banned=False,
                        memberships__is_evicted=False,
                        memberships__is_pending=False,
                    ),
                )
            )
            .order_by("group_type", "title")
        )
        serializer = PublicGroupSerializer(groups, many=True)
        return Response(serializer.data)


class PublicGroupDetailView(APIView):
    """
    GET /api/public/groups/{slug}

    Returns detailed public info for a single group.
    Includes member preview, child groups, description.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(
            Group.objects.filter(
                visibility="public",
                is_active=True,
            )
            .select_related("emblem", "sponsor_content_type")
            .annotate(
                member_count=Count(
                    "memberships",
                    filter=Q(
                        memberships__is_active=True,
                        memberships__is_banned=False,
                        memberships__is_evicted=False,
                        memberships__is_pending=False,
                    ),
                )
            ),
            slug=slug,
        )
        serializer = PublicGroupDetailSerializer(group)
        return Response(serializer.data)


class PublicGroupAdmissionStatusView(APIView):
    """
    GET /api/public/groups/{slug}/admission-status

    AllowAny — returns policy for anonymous users.
    For authenticated users, also returns their specific status.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(
            Group.objects.filter(
                visibility="public",
                is_active=True,
            ),
            slug=slug,
        )
        viewer = request.user if request.user.is_authenticated else None
        status = get_admission_status(group, viewer)
        return Response(status)


class PublicMemberProfileView(APIView):
    """
    GET /api/public/members/{username}

    Returns a lean public profile. No email, no roles, no internal fields.
    """
    permission_classes = [AllowAny]

    def get(self, request, username):
        profile = get_object_or_404(
            UserProfile.objects.select_related("user"),
            user__username=username,
            deleted_at__isnull=True,
            user__is_active=True,
        )
        serializer = PublicMemberSerializer(profile)
        return Response(serializer.data)


class PublicMemberShelvesView(APIView):
    """
    GET /api/public/members/{username}shelves/

    Returns public shelves with writing items inline.
    Anonymous: public shelves only.
    Authenticated: public + members shelves.
    """
    permission_classes = [AllowAny]

    def get(self, request, username):
        User = get_user_model()
        user_obj = get_object_or_404(User, username=username, is_active=True)

        sponsor_ct = ContentType.objects.get_for_model(User)
        allowed_visibility = ["public"]
        if request.user.is_authenticated:
            allowed_visibility.append("members")

        collections = Collection.objects.filter(
            sponsor_content_type=sponsor_ct,
            sponsor_object_id=user_obj.id,
            visibility__in=allowed_visibility,
            scope="writing",
        ).order_by("-created_at")
        ct_collection = ContentType.objects.get_for_model(Collection)
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        viewer = request.user if request.user.is_authenticated else None

        results = []
        for collection in collections:
            placements = ContentPlacement.objects.filter(
                target_content_type=ct_collection,
                target_object_id=collection.id,
                source_content_type=ct_piece,
                channel="shelf",
            ).order_by("order_index", "-created_at")

            items = []
            for placement in placements:
                if not can_view_placement(placement, viewer):
                    continue
                try:
                    payload = get_display_payload(placement)
                except Exception:
                    continue

                piece = payload.get("source")
                if not piece or getattr(piece, "status", None) != "published":
                    continue

                metadata = payload.get("metadata") or {}
                items.append({
                    "id": str(placement.id),
                    "title": metadata.get("title") or piece.title,
                    "slug": piece.slug,
                    "excerpt": metadata.get("excerpt") or getattr(piece, "excerpt", ""),
                    "writing_kind": getattr(piece, "writing_kind", None),
                    "published_at": piece.published_at,
                })

            items.sort(
                key=lambda x: x["published_at"] or timezone.datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )

            results.append({
                "id": str(collection.id),
                "title": collection.title,
                "slug": collection.slug,
                "summary": collection.summary or "",
                "visibility": collection.visibility,
                "item_count": len(items),
                "items": items,
            })

        return Response(results)


class PublicWritingPieceView(APIView):
    """
    GET /api/public/writing/{slug}

    Public reading endpoint for a single writing piece.
    Resolves artifact via placements, respects visibility.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        piece = get_object_or_404(
            WritingPiece.objects.select_related("author", "sponsor_content_type"),
            slug=slug,
            status="published",
        )

        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        placements = ContentPlacement.objects.filter(
            source_content_type=ct_piece,
            source_object_id=piece.id,
            channel__in=["feed", "shelf"],
        ).order_by("-created_at")

        viewer = request.user if request.user.is_authenticated else None
        selected = None
        for placement in placements:
            if can_view_placement(placement, viewer):
                selected = placement
                break

        if not selected:
            return Response(
                {"detail": "Not found."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        payload = get_display_payload(selected)
        metadata = payload.get("metadata") or {}

        # Build lean public response
        author_profile = getattr(piece.author, "profile", None)
        data = {
            "id": str(piece.id),
            "slug": piece.slug,
            "title": metadata.get("title") or piece.title,
            "excerpt": metadata.get("excerpt") or piece.excerpt,
            "body_json": metadata.get("body_json") or piece.body_json,
            "writing_kind": piece.writing_kind,
            "published_at": piece.published_at,
            "author": {
                "username": piece.author.username,
                "display_name": author_profile.display_name if author_profile else piece.author.username,
                "avatar_url": author_profile.avatar_url if author_profile else "",
            },
            "placement_visibility": selected.visibility,
        }

        piece.increment_view_count()
        return Response(data)


class PublicGroupCoursesView(APIView):
    """
    GET /api/public/groups/{slug}/courses

    Returns published courses for a public group.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(
            Group, slug=slug, visibility="public", is_active=True,
        )
        ct = ContentType.objects.get_for_model(Group)
        courses = Course.objects.filter(
            sponsor_content_type=ct,
            sponsor_object_id=group.id,
            status="published",
            deleted_at__isnull=True,
        ).order_by("-updated_at")

        return Response([
            {
                "id": str(c.id),
                "title": c.title,
                "slug": c.slug,
                "summary": c.summary,
                "status": c.status,
                "difficulty_level": c.difficulty_level,
                "delivery_type": c.delivery_type,
                "estimated_duration": c.estimated_duration,
                "learning_objectives": c.learning_objectives,
            }
            for c in courses
        ])


class PublicCourseDetailView(APIView):
    """
    GET /api/public/groups/{slug}/courses/{course_slug}

    Returns a published course with its outline.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug, course_slug):
        group = get_object_or_404(
            Group, slug=slug, visibility="public", is_active=True,
        )
        ct = ContentType.objects.get_for_model(Group)
        course = get_object_or_404(
            Course,
            slug=course_slug,
            sponsor_content_type=ct,
            sponsor_object_id=group.id,
            status="published",
            deleted_at__isnull=True,
        )

        items = CourseItem.objects.filter(course=course).order_by("position")
        outline = []
        for item in items:
            obj = item.content_object
            outline.append({
                "id": str(item.id),
                "position": item.position,
                "section_title": item.section_title,
                "content_type": item.content_type.model,
                "content_title": getattr(obj, "title", "") if obj else "",
                "estimated_duration": getattr(obj, "estimated_duration", None) if obj else None,
            })

        return Response({
            "id": str(course.id),
            "title": course.title,
            "slug": course.slug,
            "summary": course.summary,
            "body": course.body,
            "status": course.status,
            "difficulty_level": course.difficulty_level,
            "delivery_type": course.delivery_type,
            "estimated_duration": course.estimated_duration,
            "learning_objectives": course.learning_objectives,
            "flow_mode": course.flow_mode,
            "items": outline,
        })
