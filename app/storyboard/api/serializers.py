# storyboard/api/serializers.py

from rest_framework import serializers


class StoryboardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    grammar = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    head = serializers.JSONField(allow_null=True, required=False)
    folio_ids = serializers.SerializerMethodField()
    locked = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_folio_ids(self, obj):
        return [str(pk) for pk in obj.folios.values_list("pk", flat=True)]


class StoryboardCreateSerializer(serializers.Serializer):
    grammar = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True, default="")
    folio_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class StoryboardFolioUpdateSerializer(serializers.Serializer):
    folio_ids = serializers.ListField(child=serializers.UUIDField())


# Flat list, same convention as curation.CollectionItemSerializer -- the
# client builds the tree from parent_id, matching the existing
# CollectionItem precedent rather than nesting server-side.
class StoryboardItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    storyboard_id = serializers.UUIDField()
    parent_id = serializers.SerializerMethodField()
    rank = serializers.IntegerField()
    level = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    head = serializers.JSONField(allow_null=True, required=False)
    reference = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_parent_id(self, obj):
        return str(obj.parent_id) if obj.parent_id else None

    def get_reference(self, obj):
        if obj.reference_content_type_id is None:
            return None
        data = {
            "content_type": obj.reference_content_type.model,
            "id": str(obj.reference_object_id),
        }
        # Scene's reference is a WritingPiece -- surface its slug so the
        # client can open the editor without a second round trip. Not
        # prefetched (one extra query per referenced item); fine at Phase
        # 5's scale, revisit if a Storyboard's item count grows.
        slug = getattr(obj.reference, "slug", None)
        if slug:
            data["slug"] = slug
        return data

    def get_preview(self, obj):
        if obj.level != "scene" or obj.reference_content_type_id is None:
            return ""
        body = getattr(obj.reference, "body_text", "") or ""
        first = body.strip().split("\n", 1)[0]
        endings = [first.index(mark) + 1 for mark in (". ", "? ", "! ") if mark in first]
        if endings:
            first = first[: min(endings)]
        return first[:180]


class StoryboardItemCreateSerializer(serializers.Serializer):
    level = serializers.CharField()
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True, default="")


class StoryboardItemUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    head = serializers.JSONField(required=False, allow_null=True)
    # Presence (not just a non-null value) signals "move this item" --
    # handled in the view via `"parent_id" in request.data`.
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    rank = serializers.IntegerField(required=False)


class StoryboardReorderSerializer(serializers.Serializer):
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    ordered_item_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class SurfaceStatePatchSerializer(serializers.Serializer):
    x = serializers.FloatField(required=False, allow_null=True)
    y = serializers.FloatField(required=False, allow_null=True)
    size = serializers.ChoiceField(choices=["small", "normal", "large"], required=False)
    expanded = serializers.BooleanField(required=False)


class ParticipationCreateSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=40)
    entity_id = serializers.UUIDField(required=False)
    name = serializers.CharField(required=False, allow_blank=True, max_length=255)
    note_id = serializers.UUIDField(required=False)
    mention_index = serializers.IntegerField(required=False, min_value=0)


class NoteLinkCreateSerializer(serializers.Serializer):
    note_id = serializers.UUIDField()
