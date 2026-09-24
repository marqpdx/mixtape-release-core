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
from writing.synopsis_service import _extract_plain_text
from earthlab.models import Course, CourseItem

from django.db.models import Count, Q

from groups.models.group import Group
from groups.models.public_page import PublicPage
from groups.models.group_public_config import GroupPublicConfig
from groups.services.join_service import get_admission_status

from .serializers import (
    PublicGroupDetailSerializer,
    PublicGroupSerializer,
    PublicMemberSerializer,
)
from .writing_catalog import build_public_site_writing_catalog, browse_placements


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
                in_crossroads_directory=True,
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
    GET /api/public/groups/{group_slug}/writing/{slug}

    Group-scoped public reading endpoint for a single writing piece.
    Resolves artifacts via placements and respects visibility.
    """
    permission_classes = [AllowAny]

    def get(self, request, group_slug, slug):
        group = get_object_or_404(Group, slug=group_slug)
        group_ct = ContentType.objects.get_for_model(Group)
        piece = get_object_or_404(
            WritingPiece.objects.select_related("author", "sponsor_content_type", "synopsis"),
            slug=slug,
            status="published",
            sponsor_content_type=group_ct,
            sponsor_object_id=group.id,
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

        ct_group = ContentType.objects.get_for_model(Group)
        sponsor_group = None
        if piece.sponsor_content_type_id == ct_group.id and piece.sponsor_object_id:
            try:
                g = Group.objects.get(id=piece.sponsor_object_id)
                sponsor_group = {"slug": g.slug, "title": g.title}
            except Group.DoesNotExist:
                pass

        data = {
            "id": str(piece.id),
            "slug": piece.slug,
            "title": metadata.get("title") or piece.title,
            "excerpt": metadata.get("excerpt") or piece.excerpt,
            "public_synopsis": (
                piece.synopsis.description
                if getattr(piece, "synopsis", None)
                and piece.synopsis.public_synopsis_confirmed
                else ""
            ),
            "body_json": metadata.get("body_json") or piece.body_json,
            "writing_kind": piece.writing_kind,
            "published_at": piece.published_at,
            "author": {
                "username": piece.author.username,
                "display_name": author_profile.display_name if author_profile else piece.author.username,
                "avatar_url": author_profile.avatar_url if author_profile else "",
            },
            "placement_visibility": selected.visibility,
            "sponsor_group": sponsor_group,
        }

        piece.increment_view_count()
        return Response(data)


class PublicMemberWritingView(APIView):
    """
    GET /api/public/members/{username}/writing

    Published writing pieces authored by a member, reverse chronological.
    Anonymous: public pieces only.
    Authenticated: public + members pieces.
    """
    permission_classes = [AllowAny]

    def get(self, request, username):
        User = get_user_model()
        user_obj = get_object_or_404(User, username=username, is_active=True)
        author_profile = getattr(user_obj, "profile", None)

        allowed_visibility = ["public"]
        if request.user.is_authenticated:
            allowed_visibility.append("members")

        ct_group = ContentType.objects.get_for_model(Group)
        pieces = list(
            WritingPiece.objects
            .filter(author=user_obj, status="published")
            .select_related("author", "sponsor_content_type")
            .order_by("-published_at")
        )
        viewer = request.user if request.user.is_authenticated else None
        placements, _ = browse_placements(
            [piece.id for piece in pieces],
            viewer=viewer,
            allowed_visibilities=tuple(allowed_visibility),
        )

        results = []
        for piece in pieces:
            placement = placements.get(str(piece.id))
            if not placement:
                continue
            sponsor_group = None
            body_preview = _extract_plain_text(piece.body_json or {}, char_limit=400)
            if (
                piece.sponsor_content_type_id == ct_group.id
                and piece.sponsor_object_id
            ):
                try:
                    g = Group.objects.get(id=piece.sponsor_object_id)
                    sponsor_group = {"slug": g.slug, "title": g.title}
                except Group.DoesNotExist:
                    pass

            results.append({
                "id": str(piece.id),
                "slug": piece.slug,
                "title": piece.title,
                "excerpt": piece.excerpt or "",
                "body_preview": body_preview or piece.excerpt or "",
                "writing_kind": piece.writing_kind,
                "published_at": piece.published_at,
                "reading_time": piece.reading_time,
                "author": {
                    "username": user_obj.username,
                    "display_name": author_profile.display_name if author_profile else user_obj.username,
                },
                "sponsor_group": sponsor_group,
            })

        return Response(results)


class PublicGroupWritingView(APIView):
    """
    GET /api/public/groups/{slug}/writing

    Published writing pieces sponsored by a group, reverse chronological.
    AllowAny — public visibility only. No authentication required.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug, is_active=True, visibility="public")

        ct_group = ContentType.objects.get_for_model(Group)

        pieces = list(
            WritingPiece.objects
            .filter(
                sponsor_content_type=ct_group,
                sponsor_object_id=group.id,
                status="published",
            )
            .select_related("author")
            .order_by("-published_at")
        )
        placements, _ = browse_placements([piece.id for piece in pieces])

        results = []
        for piece in pieces:
            placement = placements.get(str(piece.id))
            if not placement:
                continue
            author = piece.author
            author_profile = getattr(author, "profile", None) if author else None
            body_preview = _extract_plain_text(piece.body_json or {}, char_limit=400)
            results.append({
                "id": str(piece.id),
                "slug": piece.slug,
                "title": piece.title,
                "excerpt": piece.excerpt or "",
                "body_preview": body_preview or piece.excerpt or "",
                "writing_kind": piece.writing_kind,
                "published_at": piece.published_at,
                "reading_time": piece.reading_time,
                "author": {
                    "username": author.username if author else "",
                    "display_name": author_profile.display_name if author_profile else (author.username if author else ""),
                },
                "sponsor_group": {"slug": group.slug, "title": group.title},
            })

        return Response(results)


class PublicSiteWritingView(APIView):
    """
    GET /api/public/sites/writing?owner={username}&groups={slug,slug}

    Returns one deduplicated public writing catalog for a site owner and a
    bounded set of group sponsors. Aggregation and visibility stay server-side.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        owner_username = (request.query_params.get("owner") or "").strip()
        if not owner_username:
            return Response(
                {"detail": "The owner query parameter is required."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        group_slugs = []
        for value in request.query_params.getlist("group"):
            group_slugs.extend(value.split(","))
        group_slugs.extend((request.query_params.get("groups") or "").split(","))
        group_slugs = list(
            dict.fromkeys(slug.strip() for slug in group_slugs if slug.strip())
        )
        if len(group_slugs) > 10:
            return Response(
                {"detail": "A public site may aggregate at most 10 groups."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()
        owner = get_object_or_404(
            User.objects.select_related("profile"),
            username=owner_username,
            is_active=True,
        )
        groups = list(
            Group.objects.filter(
                slug__in=group_slugs,
                visibility="public",
                is_active=True,
            ).order_by("title")
        )
        found_slugs = {group.slug for group in groups}
        missing_slugs = [slug for slug in group_slugs if slug not in found_slugs]
        if missing_slugs:
            return Response(
                {
                    "detail": "One or more public groups were not found.",
                    "missing_groups": missing_slugs,
                },
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        items, facets = build_public_site_writing_catalog(owner=owner, groups=groups)

        category = request.query_params.get("category")
        collection = request.query_params.get("collection")
        tag = request.query_params.get("tag")
        writing_kind = request.query_params.get("kind")
        year_value = request.query_params.get("year")
        if category:
            items = [
                item
                for item in items
                if category in {row["key"] for row in item["categories"]}
            ]
        if collection:
            items = [
                item
                for item in items
                if collection in {row["key"] for row in item["collections"]}
            ]
        if tag:
            items = [
                item
                for item in items
                if tag in {row["slug"] for row in item["tags"]}
            ]
        if writing_kind:
            items = [item for item in items if item["writing_kind"] == writing_kind]
        if year_value:
            try:
                year = int(year_value)
            except ValueError:
                return Response(
                    {"detail": "The year query parameter must be an integer."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            items = [
                item for item in items
                if item["published_at"] and item["published_at"].year == year
            ]

        try:
            limit = min(max(int(request.query_params.get("limit", 24)), 1), 100)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except ValueError:
            return Response(
                {"detail": "The limit and offset query parameters must be integers."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        profile = getattr(owner, "profile", None)
        count = len(items)
        return Response({
            "site": {
                "owner": {
                    "username": owner.username,
                    "display_name": profile.display_name if profile else owner.username,
                },
                "groups": [
                    {"slug": group.slug, "title": group.title}
                    for group in groups
                ],
            },
            "count": count,
            "limit": limit,
            "offset": offset,
            "items": items[offset:offset + limit],
            "facets": {
                "categories": facets["categories"],
                "collections": facets["collections"],
                "tags": facets["tags"],
                "archives": facets["archives"],
            },
        })


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


class PublicWritingRunView(APIView):
    """
    GET /api/public/writing/runs/{slug}

    Public reader view for a published WritingRun.
    Returns Run metadata and ordered member Doc list for the sequential reader.
    ADR-0054 P1-10.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        from writing.models import WritingRun
        run = get_object_or_404(WritingRun, slug=slug, status="published")

        memberships = run.memberships.select_related("piece__author").order_by("order_index")

        pieces = []
        for m in memberships:
            piece = m.piece
            if piece.status != "published":
                continue
            author_profile = getattr(piece.author, "profile", None)
            pieces.append({
                "order_index": m.order_index,
                "piece_id": str(piece.id),
                "piece_slug": piece.slug,
                "piece_title": piece.title,
                "piece_excerpt": piece.excerpt,
                "published_at": piece.published_at,
                "author": {
                    "username": piece.author.username,
                    "display_name": author_profile.display_name if author_profile else piece.author.username,
                },
            })

        return Response({
            "id": str(run.id),
            "slug": run.slug,
            "title": run.title,
            "status": run.status,
            "published_at": run.published_at,
            "piece_count": len(pieces),
            "pieces": pieces,
        })


class PublicGroupPageView(APIView):
    """
    GET /api/public/groups/<slug>/page

    Returns the published content snapshot for a group's Crossroads Page.
    AllowAny — no authentication required. Returns 404 if no published page
    exists for the group.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(Group, slug=slug)
        try:
            page = group.public_page
        except PublicPage.DoesNotExist:
            return Response(
                {"detail": "This group has no public page."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        if page.status != PublicPage.Status.PUBLISHED:
            return Response(
                {"detail": "This group has no published public page."},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        components = [
            {
                "id": c.id,
                "slot": c.slot,
                "component_type": c.component_type,
                "content_json": c.content_json,
                "sort_order": c.sort_order,
            }
            for c in page.components.all()
        ]

        return Response({
            "group_slug": group.slug,
            "group_id": str(group.id),
            "status": page.status,
            "layout_template": page.layout_template,
            "content": page.published_content,
            "components": components,
            "published_at": page.published_at,
        })


class CatalystIntakeView(APIView):
    """
    POST /api/public/client-intake

    Ersatz intake form for the Catalyst pilot. Creates a BusinessProspect
    record (status=new) for admin review and activation. Disabled via
    INTAKE_FORM_ENABLED=False in settings.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        from django.conf import settings
        if not getattr(settings, "INTAKE_FORM_ENABLED", False):
            return Response({"detail": "Not found."}, status=drf_status.HTTP_404_NOT_FOUND)

        from django.utils.text import slugify
        from prospects.models import BusinessProspect

        org_name = request.data.get("org_name", "").strip()
        email = request.data.get("email", "").strip()
        org_description = request.data.get("org_description", "").strip()
        knowledge_goal = request.data.get("knowledge_goal", "").strip()

        if not org_name:
            return Response({"detail": "org_name is required."}, status=drf_status.HTTP_400_BAD_REQUEST)
        if not email:
            return Response({"detail": "email is required."}, status=drf_status.HTTP_400_BAD_REQUEST)

        from groups.models.group import Group as CatalystGroup

        base_slug = slugify(org_name)
        slug = base_slug
        counter = 1
        while (
            BusinessProspect.objects.filter(slug=slug).exists()
            or CatalystGroup.objects.filter(slug=slug).exists()
        ):
            slug = f"{base_slug}-{counter}"
            counter += 1

        BusinessProspect.objects.create(
            name=org_name,
            slug=slug,
            primary_contact_email=email,
            org_description=org_description,
            knowledge_goal=knowledge_goal,
            status="new",
        )

        return Response({"detail": "Request received."}, status=drf_status.HTTP_201_CREATED)


class PublicGroupLandingConfigView(APIView):
    """
    GET /api/public/groups/<slug>/public-config

    Returns the Group's public landing configuration. AllowAny.

    T1 (no GroupPublicConfig): synthesizes a payload from Group data and latest
    published writing. Frontend renders the T1 surface (background image banner +
    group name + writing grid).

    T2 (active GroupPublicConfig with rows): returns the config plus resolved
    featured content. Frontend renders from rows when rows is non-null.

    Server-side enforcement (Decision 9): only published WritingPiece artifacts
    are returned regardless of tier. Frontend never decides visibility.
    """
    permission_classes = [AllowAny]

    def get(self, request, slug):
        group = get_object_or_404(
            Group.objects.filter(visibility="public", is_active=True),
            slug=slug,
        )

        group_block = {
            "id": str(group.id),
            "slug": group.slug,
            "title": group.title,
            "description": group.description or "",
            "summary": group.summary or "",
            "tagline": group.tagline or "",
            "profile_image_url": group.profile_image_url,
            "background_image_url": group.background_image_url,
        }

        # T1 path — no config or inactive config
        try:
            config = group.public_config
            config_active = config.is_active
        except GroupPublicConfig.DoesNotExist:
            config = None
            config_active = False

        if config is None or not config_active:
            latest_pieces = self._latest_group_writing(group, limit=6)
            t1_presentation = None
            if config is not None:
                t1_presentation = {
                    "typography_setting": config.typography_setting or "journal",
                    "template_id": config.template_id or None,
                    "palette_id": config.palette_id or None,
                    "font_id": config.font_id or None,
                }
            return Response({
                "tier": "t1",
                "group": group_block,
                "presentation": t1_presentation,
                "hero": None,
                "featured_content": {
                    "type": "writing",
                    "layout": "grid",
                    "collection_id": None,
                    "pieces": latest_pieces,
                },
                "about": {"text": group.summary or "", "descriptors": []},
                "engagement": {"text": "", "capability_pills": [], "cta": {"label": "", "action": ""}},
                "subscription": {"list_slug": None, "has_list": False},
                "rows": None,
                "generation_status": "none",
            })

        # T2 path — active config
        featured_pieces = self._resolve_featured_content(config)
        subscription_list_slug = (
            config.subscription_list.listmonk_name
            if config.subscription_list
            else None
        )

        return Response({
            "tier": "t2",
            "group": group_block,
            "presentation": {
                "typography_setting": config.typography_setting or "journal",
                "template_id": config.template_id or None,
                "palette_id": config.palette_id or None,
                "font_id": config.font_id or None,
            },
            "hero": {
                "eyebrow": config.hero_eyebrow,
                "headline": config.hero_headline,
                "body": config.hero_body,
                "primary_cta": {
                    "label": config.hero_primary_cta_label,
                    "action": config.hero_primary_cta_action,
                },
                "secondary_cta": {
                    "label": config.hero_secondary_cta_label,
                    "action": config.hero_secondary_cta_action,
                },
            },
            "featured_content": {
                "type": config.featured_content_type,
                "layout": config.featured_layout,
                "collection_id": str(config.featured_collection_id) if config.featured_collection_id else None,
                "pieces": featured_pieces,
            },
            "about": {
                "text": config.about_text,
                "descriptors": config.about_descriptors,
            },
            "engagement": {
                "text": config.engagement_text,
                "capability_pills": config.engagement_capability_pills,
                "cta": {
                    "label": config.engagement_cta_label,
                    "action": config.engagement_cta_action,
                },
            },
            "subscription": {
                "list_slug": subscription_list_slug,
                "has_list": subscription_list_slug is not None,
            },
            "rows": config.rows,
            "generation_status": config.generation_status,
        })

    def _latest_group_writing(self, group: Group, limit: int = 6) -> list:
        """Fetch the most recent published WritingPieces for a T1 group surface."""
        ct_group = ContentType.objects.get_for_model(Group)
        pieces = (
            WritingPiece.objects
            .filter(
                sponsor_content_type=ct_group,
                sponsor_object_id=group.id,
                status="published",
            )
            .select_related("author")
            .order_by("-published_at")[:limit]
        )
        result = []
        for piece in pieces:
            author = piece.author
            author_profile = getattr(author, "profile", None) if author else None
            result.append({
                "id": str(piece.id),
                "slug": piece.slug,
                "title": piece.title,
                "excerpt": piece.excerpt or "",
                "writing_kind": piece.writing_kind,
                "published_at": piece.published_at,
                "reading_time": piece.reading_time,
                "author": {
                    "username": author.username if author else "",
                    "display_name": (
                        author_profile.display_name
                        if author_profile
                        else (author.username if author else "")
                    ),
                },
            })
        return result

    def _resolve_featured_content(self, config: GroupPublicConfig) -> list:
        """
        Resolve featured WritingPieces. Collection-backed path is preferred
        (Decision 4); falls back to explicit ordered IDs if no collection is set.

        Only returns pieces where status=published. No private content leaks
        through this path regardless of what the config references.
        """
        ct_piece = ContentType.objects.get_for_model(WritingPiece)
        piece_ids: list = []

        if config.featured_collection_id:
            from curation.models import CollectionItem
            items = (
                CollectionItem.objects
                .filter(
                    collection_id=config.featured_collection_id,
                    content_type=ct_piece,
                    is_hidden=False,
                    is_folder=False,
                )
                .order_by("order_index")
                .values_list("content_object_id", flat=True)
            )
            piece_ids = list(items)
        elif config.featured_item_ids:
            piece_ids = config.featured_item_ids

        if not piece_ids:
            return []

        pieces_by_id = {
            str(p.id): p
            for p in WritingPiece.objects.filter(
                id__in=piece_ids,
                status="published",
            ).select_related("author")
        }

        result = []
        for pid in piece_ids:
            piece = pieces_by_id.get(str(pid))
            if not piece:
                continue
            author = piece.author
            author_profile = getattr(author, "profile", None) if author else None
            result.append({
                "id": str(piece.id),
                "slug": piece.slug,
                "title": piece.title,
                "excerpt": piece.excerpt or "",
                "writing_kind": piece.writing_kind,
                "published_at": piece.published_at,
                "reading_time": piece.reading_time,
                "author": {
                    "username": author.username if author else "",
                    "display_name": (
                        author_profile.display_name
                        if author_profile
                        else (author.username if author else "")
                    ),
                },
            })

        return result
