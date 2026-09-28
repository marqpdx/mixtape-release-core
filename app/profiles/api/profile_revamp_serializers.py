# profiles/api/profile_revamp_serializers.py

from datetime import date
from django.contrib.auth import get_user_model
from rest_framework import serializers

from profiles.models import (
    UserProfile, ProfileTheme, PinnedShowcase, PinnedTrack,
    NowPlaying, QAItem, Badge, FeaturedLink,
    KNOWN_SECTION_IDS, DEFAULT_SECTION_LAYOUT,
    ThemeChoices,
)
from utils.storage.storage_utils import key_to_url, public_key_to_url

User = get_user_model()

THEME_ACCENTS = {
    'paper':  ['#c2410c', '#1d4ed8', '#15803d', '#a16207', '#7c3aed', '#be123c'],
    'noir':   ['#fde68a', '#fb7185', '#22d3ee', '#a78bfa', '#84cc16', '#fb923c'],
    'garden': ['#4d7c0f', '#9a3412', '#0f766e', '#a16207', '#6d28d9', '#1d4ed8'],
    'neon':   ['#22d3ee', '#f472b6', '#a78bfa', '#facc15', '#34d399', '#fb7185'],
    'sunset': ['#db2777', '#ea580c', '#7c3aed', '#0ea5e9', '#16a34a', '#ca8a04'],
}


class PinnedTrackSerializer(serializers.ModelSerializer):
    class Meta:
        model = PinnedTrack
        fields = ['position', 'label', 'name', 'duration']


class PinnedShowcaseSerializer(serializers.ModelSerializer):
    tracks = PinnedTrackSerializer(many=True, read_only=True)

    class Meta:
        model = PinnedShowcase
        fields = ['kind', 'label', 'title', 'subtitle', 'mark', 'cover', 'cta_target', 'tracks']


class NowPlayingSerializer(serializers.ModelSerializer):
    class Meta:
        model = NowPlaying
        fields = ['track', 'artist', 'label', 'source', 'updated_at']


class QAItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = QAItem
        fields = ['position', 'q', 'a']


class BadgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Badge
        fields = ['glyph', 'text', 'featured', 'earned_at']


class FeaturedLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeaturedLink
        fields = ['position', 'icon', 'title', 'sub', 'url']


def _joined_display(user):
    """Format date_joined as 'mon 'YY'."""
    dt = user.date_joined
    return f"{dt.strftime('%b').lower()} '{dt.strftime('%y')}"


def _follower_count(profile):
    """Return follower count — returns 0 until a follow system is wired."""
    try:
        return profile.followers.count()
    except Exception:
        return 0


def _following_count(profile):
    try:
        return profile.user.following.count()
    except Exception:
        return 0


def _mixtape_count(profile):
    try:
        return profile.mixtapes.count()
    except Exception:
        return 0


class PublicProfileSerializer(serializers.ModelSerializer):
    username      = serializers.CharField(source='user.username', read_only=True)
    displayName   = serializers.CharField(source='display_name', read_only=True)
    role          = serializers.SerializerMethodField()
    bio           = serializers.CharField(source='bio_markdown', read_only=True)
    quickIntro    = serializers.CharField(source='quick_intro', read_only=True)
    status        = serializers.CharField(source='right_now', read_only=True)
    skills        = serializers.SerializerMethodField()
    workAreas     = serializers.SerializerMethodField()
    whoAreYou     = serializers.CharField(source='who_are_you', read_only=True)
    whyAreYouHere = serializers.CharField(source='why_are_you_here', read_only=True)
    quickLink     = serializers.CharField(source='quick_link', read_only=True)
    avatarUrl           = serializers.SerializerMethodField()
    backgroundImageUrl  = serializers.SerializerMethodField()
    introVoiceUrl       = serializers.SerializerMethodField()
    introVoiceTranscript = serializers.CharField(source='intro_voice_transcript', read_only=True)
    theme               = serializers.SerializerMethodField()
    accent        = serializers.SerializerMethodField()
    font          = serializers.SerializerMethodField()
    background    = serializers.SerializerMethodField()
    avatarShape   = serializers.SerializerMethodField()
    density       = serializers.SerializerMethodField()
    decorations   = serializers.SerializerMethodField()
    avatarSticker = serializers.SerializerMethodField()
    stats         = serializers.SerializerMethodField()
    sectionLayout = serializers.SerializerMethodField()
    pinned        = serializers.SerializerMethodField()
    nowPlaying    = serializers.SerializerMethodField()
    activity      = serializers.SerializerMethodField()
    friends       = serializers.SerializerMethodField()
    qa            = serializers.SerializerMethodField()
    badges        = serializers.SerializerMethodField()
    links         = serializers.SerializerMethodField()
    version       = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = [
            'username', 'displayName', 'role', 'bio', 'quickIntro', 'status',
            'skills', 'workAreas', 'whoAreYou', 'whyAreYouHere', 'quickLink',
            'avatarUrl', 'backgroundImageUrl',
            'introVoiceUrl', 'introVoiceTranscript',
            'theme', 'accent', 'font', 'background', 'avatarShape', 'density',
            'decorations', 'avatarSticker', 'stats', 'sectionLayout',
            'pinned', 'nowPlaying', 'activity', 'friends', 'qa', 'badges', 'links', 'version',
        ]

    def _theme_config(self, obj):
        try:
            return obj.theme_config
        except ProfileTheme.DoesNotExist:
            return None

    def get_role(self, obj):
        parts = [p for p in [obj.practice_area, obj.location] if p]
        return ' · '.join(parts)

    def get_skills(self, obj):
        if not obj.skills:
            return []
        return [s.strip() for s in obj.skills.split(',') if s.strip()]

    def get_workAreas(self, obj):
        if not obj.work_areas:
            return []
        return [s.strip() for s in obj.work_areas.split(',') if s.strip()]

    def get_avatarUrl(self, obj):
        # profile_image is genuinely public (visible to anyone who can see
        # the profile) -- see reference/patterns/image-handling-cheatsheet.md
        if obj.profile_image:
            return public_key_to_url(obj.profile_image)
        return obj.avatar_url or None

    def get_backgroundImageUrl(self, obj):
        if obj.background_image:
            return public_key_to_url(obj.background_image)
        return None

    def get_introVoiceUrl(self, obj):
        return key_to_url(obj.intro_voice) if obj.intro_voice else None

    def get_theme(self, obj):
        tc = self._theme_config(obj)
        return tc.theme if tc else 'paper'

    def get_accent(self, obj):
        tc = self._theme_config(obj)
        return tc.accent if tc else '#c2410c'

    def get_font(self, obj):
        tc = self._theme_config(obj)
        return tc.font if tc else 'editorial'

    def get_background(self, obj):
        tc = self._theme_config(obj)
        return tc.background if tc else 'paper'

    def get_avatarShape(self, obj):
        tc = self._theme_config(obj)
        return tc.avatar_shape if tc else 'rounded'

    def get_density(self, obj):
        tc = self._theme_config(obj)
        return tc.density if tc else 'cozy'

    def get_decorations(self, obj):
        tc = self._theme_config(obj)
        return tc.decorations if tc else True

    def get_avatarSticker(self, obj):
        tc = self._theme_config(obj)
        return tc.avatar_sticker if tc else ''

    def get_stats(self, obj):
        return {
            'followers': str(_follower_count(obj)),
            'following': str(_following_count(obj)),
            'mixtapes': _mixtape_count(obj),
            'joined': _joined_display(obj.user),
        }

    def get_sectionLayout(self, obj):
        tc = self._theme_config(obj)
        if tc and tc.section_layout:
            return tc.section_layout
        return DEFAULT_SECTION_LAYOUT

    def get_pinned(self, obj):
        try:
            return PinnedShowcaseSerializer(obj.pinned_showcase).data
        except Exception:
            return None

    def get_nowPlaying(self, obj):
        try:
            return NowPlayingSerializer(obj.now_playing).data
        except Exception:
            return None

    def get_activity(self, obj):
        from activity.models import Action
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(User)
        qs = Action.objects.filter(
            actor_content_type=ct,
            actor_id=str(obj.user.pk),
        ).order_by('-occurs_at')[:10]
        return [
            {'when': a.occurs_at.isoformat(), 'verb': a.verb, 'what': str(a)}
            for a in qs
        ]

    def get_friends(self, obj):
        return []

    def get_qa(self, obj):
        return QAItemSerializer(obj.qa_items.all(), many=True).data

    def get_badges(self, obj):
        return BadgeSerializer(obj.badges.all(), many=True).data

    def get_links(self, obj):
        return FeaturedLinkSerializer(obj.featured_links.all(), many=True).data

    def get_version(self, obj):
        tc = self._theme_config(obj)
        return tc.version if tc else 1


class ProfileThemeWriteSerializer(serializers.ModelSerializer):
    """Validates and writes theme config fields."""

    class Meta:
        model = ProfileTheme
        fields = [
            'theme', 'accent', 'font', 'background',
            'avatar_shape', 'density', 'decorations', 'avatar_sticker',
        ]

    def validate(self, data):
        theme = data.get('theme', self.instance.theme if self.instance else 'paper')
        accent = data.get('accent')
        if accent and accent not in THEME_ACCENTS.get(theme, []):
            raise serializers.ValidationError(
                {'accent': f'{accent} is not a valid accent for the {theme} theme.'}
            )
        return data


class SectionLayoutSerializer(serializers.Serializer):
    layout = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()),
        min_length=len(KNOWN_SECTION_IDS),
        max_length=len(KNOWN_SECTION_IDS),
    )

    def validate_layout(self, value):
        ids = [item.get('id') for item in value]
        if sorted(ids) != sorted(KNOWN_SECTION_IDS):
            raise serializers.ValidationError('layout must contain exactly one entry per known section id.')
        if ids[0] != 'header':
            raise serializers.ValidationError('header must be first in layout.')
        first = next((item for item in value if item.get('id') == 'header'), None)
        if first and str(first.get('visible', 'true')).lower() == 'false':
            raise serializers.ValidationError('header section must always be visible.')
        return value


class PinnedShowcaseWriteSerializer(serializers.ModelSerializer):
    tracks = PinnedTrackSerializer(many=True)

    class Meta:
        model = PinnedShowcase
        fields = ['kind', 'label', 'title', 'subtitle', 'mark', 'cta_target', 'tracks']

    def upsert(self, profile):
        tracks_data = self.validated_data.pop('tracks', [])
        showcase, _ = PinnedShowcase.objects.update_or_create(
            profile=profile,
            defaults=self.validated_data,
        )
        showcase.tracks.all().delete()
        for td in tracks_data:
            PinnedTrack.objects.create(showcase=showcase, **td)
        return showcase


class NowPlayingWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = NowPlaying
        fields = ['track', 'artist', 'label', 'source', 'source_id']

    def upsert(self, profile):
        obj, _ = NowPlaying.objects.update_or_create(
            profile=profile,
            defaults=self.validated_data,
        )
        return obj


class QAItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = QAItem
        fields = ['position', 'q', 'a']


class FeaturedLinkWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeaturedLink
        fields = ['position', 'icon', 'title', 'sub', 'url']
