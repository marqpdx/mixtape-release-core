# commons/api/serializers.py

from rest_framework import serializers

from commons.models import CommonsItem, Filament


class CommonsItemListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    recommended_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CommonsItem
        fields = [
            "id",
            "title",
            "slug",
            "item_type",
            "curation_status",
            "summary",
            "location_name",
            "latitude",
            "longitude",
            "website",
            "source_url",
            "recommended_by_name",
            "created_at",
            "updated_at",
        ]

    def get_recommended_by_name(self, obj):
        if obj.recommended_by:
            return getattr(obj.recommended_by, "display_name", str(obj.recommended_by))
        return None


class CommonsItemDetailSerializer(CommonsItemListSerializer):
    """Full detail serializer with all fields."""

    curated_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    filaments_out = serializers.SerializerMethodField()
    filaments_in = serializers.SerializerMethodField()

    class Meta(CommonsItemListSerializer.Meta):
        fields = list(CommonsItemListSerializer.Meta.fields) + [
            "body",
            "why_recommended",
            "contact_email",
            "contact_links",
            "instagram",
            "youtube",
            "rss",
            "founder",
            "extracted_data",
            "additional_data",
            "curated_by_name",
            "approved_by_name",
            "published_at",
        ]

    def get_curated_by_name(self, obj):
        if obj.curated_by:
            return getattr(obj.curated_by, "display_name", str(obj.curated_by))
        return None

    def get_approved_by_name(self, obj):
        if obj.approved_by:
            return getattr(obj.approved_by, "display_name", str(obj.approved_by))
        return None

    def get_filaments_out(self, obj):
        return FilamentSerializer(obj.filaments_out.all(), many=True).data

    def get_filaments_in(self, obj):
        return FilamentSerializer(obj.filaments_in.all(), many=True).data


class CommonsItemCreateSerializer(serializers.Serializer):
    """Validation serializer for item capture."""

    source_url = serializers.URLField(required=False, allow_blank=True, default="")
    title = serializers.CharField(required=False, allow_blank=True, default="")
    why_recommended = serializers.CharField(required=False, allow_blank=True, default="")
    item_type = serializers.ChoiceField(
        choices=CommonsItem.ItemType.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    location_name = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, data):
        if not data.get("source_url") and not data.get("title"):
            raise serializers.ValidationError(
                "Either source_url or title must be provided."
            )
        return data


class CommonsItemCurationSerializer(serializers.ModelSerializer):
    """Write serializer for curation edits."""

    class Meta:
        model = CommonsItem
        fields = [
            "title",
            "summary",
            "body",
            "item_type",
            "why_recommended",
            "website",
            "contact_email",
            "contact_links",
            "instagram",
            "youtube",
            "rss",
            "location_name",
            "latitude",
            "longitude",
            "founder",
            "additional_data",
        ]
        extra_kwargs = {field: {"required": False} for field in fields}


class FilamentSerializer(serializers.ModelSerializer):
    source_title = serializers.CharField(source="source.title", read_only=True)
    target_title = serializers.CharField(source="target.title", read_only=True)

    class Meta:
        model = Filament
        fields = [
            "id",
            "source",
            "source_title",
            "target",
            "target_title",
            "relation_type",
            "note",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class FilamentCreateSerializer(serializers.Serializer):
    """Validation for creating a filament from a source item's detail view."""

    target_id = serializers.UUIDField()
    relation_type = serializers.ChoiceField(choices=Filament.RelationType.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
