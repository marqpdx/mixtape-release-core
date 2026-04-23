# commons/api/serializers.py

from rest_framework import serializers

from commons.models import CommonsItem


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
            "filaments_out",
            "filaments_in",
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
        from relations.service import RelationshipService
        return [_serialize_commons_relationship(r) for r in RelationshipService.get_outgoing(obj, domain="commons")]

    def get_filaments_in(self, obj):
        from relations.service import RelationshipService
        return [_serialize_commons_relationship(r) for r in RelationshipService.get_incoming(obj, domain="commons")]


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


COMMONS_VERB_CHOICES = [
    ("founded-by", "Founded By"),
    ("located-in", "Located In"),
    ("collaborates-with", "Collaborates With"),
    ("teaches-at", "Teaches At"),
    ("inspired-by", "Inspired By"),
    ("affiliated-with", "Affiliated With"),
    ("program-of", "Program Of"),
]


def _serialize_commons_relationship(r):
    endpoint_map = {}
    for ct_id, obj_id, obj in [
        (r.source_content_type_id, str(r.source_object_id), r.source),
        (r.target_content_type_id, str(r.target_object_id), r.target),
    ]:
        endpoint_map[(ct_id, obj_id)] = obj

    source = r.source
    target = r.target
    return {
        "id": str(r.id),
        "source": str(r.source_object_id),
        "source_title": getattr(source, "title", None) if source else None,
        "target": str(r.target_object_id),
        "target_title": getattr(target, "title", None) if target else None,
        "relation_type": r.relationship_type.slug,
        "note": r.notes,
        "created_at": r.created_at,
    }


class FilamentCreateSerializer(serializers.Serializer):
    """Validation for creating a commons-domain Relationship from a CommonsItem."""

    target_id = serializers.UUIDField()
    relation_type = serializers.ChoiceField(choices=COMMONS_VERB_CHOICES)
    note = serializers.CharField(required=False, allow_blank=True, default="")
