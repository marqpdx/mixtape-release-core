# storyboard/api/serializers.py

from rest_framework import serializers


class StoryboardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    grammar = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    head = serializers.JSONField(allow_null=True, required=False)
    folio_id = serializers.SerializerMethodField()
    locked = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_folio_id(self, obj):
        return str(obj.folio_id) if obj.folio_id else None


class StoryboardCreateSerializer(serializers.Serializer):
    grammar = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True, default="")
    folio_id = serializers.UUIDField(required=False, allow_null=True)


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
