# profiles/api/profile_revamp_views.py

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from profiles.models import (
    UserProfile, ProfileTheme, QAItem, FeaturedLink,
    DEFAULT_SECTION_LAYOUT, KNOWN_SECTION_IDS,
)
from .profile_revamp_serializers import (
    PublicProfileSerializer,
    ProfileThemeWriteSerializer,
    SectionLayoutSerializer,
    PinnedShowcaseWriteSerializer,
    NowPlayingWriteSerializer,
    QAItemWriteSerializer,
    FeaturedLinkWriteSerializer,
)


def _get_or_create_theme(profile):
    tc, _ = ProfileTheme.objects.get_or_create(
        profile=profile,
        defaults={'section_layout': list(DEFAULT_SECTION_LAYOUT)},
    )
    return tc


class PublicProfileView(generics.GenericAPIView):
    """GET /api/profiles/{username} — public, cached."""
    permission_classes = [AllowAny]

    def get(self, request, username):
        profile = get_object_or_404(
            UserProfile.objects.select_related('user', 'theme_config'),
            user__username=username,
        )
        serializer = PublicProfileSerializer(profile)
        response = Response(serializer.data)
        response['Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=300'
        return response


class MeProfileView(generics.GenericAPIView):
    """GET/PATCH /api/me/profile/new — authenticated owner."""
    permission_classes = [IsAuthenticated]

    def _get_profile(self, request):
        return get_object_or_404(UserProfile, user=request.user)

    def get(self, request):
        profile = self._get_profile(request)
        _get_or_create_theme(profile)
        return Response(PublicProfileSerializer(profile).data)

    @transaction.atomic
    def patch(self, request):
        profile = self._get_profile(request)
        tc = _get_or_create_theme(profile)

        # Separate theme fields from copy fields
        theme_fields = {'theme', 'accent', 'font', 'background', 'avatar_shape', 'density', 'decorations', 'avatar_sticker'}
        copy_fields   = {'display_name', 'bio_markdown', 'right_now'}

        theme_data = {k: v for k, v in request.data.items() if k in theme_fields}
        copy_data  = {k: v for k, v in request.data.items() if k in copy_fields}

        if theme_data:
            serializer = ProfileThemeWriteSerializer(tc, data=theme_data, partial=True)
            serializer.is_valid(raise_exception=True)
            # Snap accent when theme changes
            if 'theme' in theme_data and 'accent' not in theme_data:
                from .profile_revamp_serializers import THEME_ACCENTS
                serializer.validated_data['accent'] = THEME_ACCENTS[theme_data['theme']][0]
            tc = serializer.save()
            tc.version += 1
            tc.save(update_fields=['version'])

        if copy_data:
            for field, value in copy_data.items():
                setattr(profile, field, value)
            profile.save(update_fields=list(copy_data.keys()))

        return Response(PublicProfileSerializer(profile).data)


class MeSectionsView(generics.GenericAPIView):
    """PUT /api/me/profile/new/sections — bulk replace section layout."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        tc = _get_or_create_theme(profile)

        serializer = SectionLayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        layout = serializer.validated_data['layout']
        # Normalize visible to bool
        normalized = [
            {'id': item['id'], 'visible': str(item.get('visible', 'true')).lower() != 'false'}
            for item in layout
        ]
        tc.section_layout = normalized
        tc.version += 1
        tc.save(update_fields=['section_layout', 'version'])

        return Response(PublicProfileSerializer(profile).data)


class MePinnedView(generics.GenericAPIView):
    """PUT /api/me/profile/new/pinned — upsert pinned showcase."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        serializer = PinnedShowcaseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.upsert(profile)
        return Response(PublicProfileSerializer(profile).data)


class MeNowPlayingView(generics.GenericAPIView):
    """PUT /api/me/profile/new/now-playing — upsert now playing."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        serializer = NowPlayingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.upsert(profile)
        return Response(PublicProfileSerializer(profile).data)


class MeQAView(generics.GenericAPIView):
    """PUT /api/me/profile/new/qa — bulk replace Q&A items."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        items_data = request.data if isinstance(request.data, list) else request.data.get('items', [])
        serializer = QAItemWriteSerializer(data=items_data, many=True)
        serializer.is_valid(raise_exception=True)

        profile.qa_items.all().delete()
        for item in serializer.validated_data:
            QAItem.objects.create(profile=profile, **item)

        return Response(PublicProfileSerializer(profile).data)


class MeLinksView(generics.GenericAPIView):
    """PUT /api/me/profile/new/links — bulk replace featured links."""
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        items_data = request.data if isinstance(request.data, list) else request.data.get('items', [])
        serializer = FeaturedLinkWriteSerializer(data=items_data, many=True)
        serializer.is_valid(raise_exception=True)

        profile.featured_links.all().delete()
        for item in serializer.validated_data:
            FeaturedLink.objects.create(profile=profile, **item)

        return Response(PublicProfileSerializer(profile).data)


class MePublishView(generics.GenericAPIView):
    """POST /api/me/profile/new/publish — bump version; triggers ISR revalidation."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        tc = _get_or_create_theme(profile)
        tc.version += 1
        tc.save(update_fields=['version'])
        return Response({'status': 'published', 'version': tc.version})
