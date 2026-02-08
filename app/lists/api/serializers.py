from rest_framework import serializers

from lists.models import List, ListItemAnnotation
from lists.parser import count_items, parse_list_text
from utils.shared.contenttypes import resolve_content_type


class ListSerializer(serializers.ModelSerializer):
    """Serializer for List model."""

    sponsor_content_type = serializers.CharField(write_only=True, required=False)
    sponsor_object_id = serializers.UUIDField(required=False)
    sponsor_type = serializers.SerializerMethodField(read_only=True)
    items = serializers.SerializerMethodField(read_only=True)
    stats = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = List
        fields = [
            "id",
            "title",
            "summary",
            "slug",
            "body_text",
            "items",
            "stats",
            "sponsor_content_type",
            "sponsor_object_id",
            "sponsor_type",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "items",
            "stats",
            "sponsor_type",
            "created_at",
            "updated_at",
        ]

    def get_sponsor_type(self, obj):
        return obj.sponsor_type

    def get_items(self, obj):
        """Parse body_text and return structured items."""
        items = parse_list_text(obj.body_text)
        return [item.to_dict() for item in items]

    def get_stats(self, obj):
        """Return item counts."""
        items = parse_list_text(obj.body_text)
        return count_items(items)

    def validate(self, attrs):
        data = super().validate(attrs)
        raw_ct = self.initial_data.get("sponsor_content_type")
        raw_obj = self.initial_data.get("sponsor_object_id")
        if raw_ct:
            if not raw_obj:
                raise serializers.ValidationError(
                    {"sponsor_object_id": "Sponsor object id is required."}
                )
            data["sponsor_content_type"] = resolve_content_type(raw_ct)
        return data


class ListCreateSerializer(serializers.Serializer):
    """Serializer for creating a new list."""

    title = serializers.CharField(max_length=100)
    body_text = serializers.CharField(required=False, allow_blank=True, default="")
    sponsor_content_type = serializers.CharField(required=False)
    sponsor_object_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        data = super().validate(attrs)
        raw_ct = self.initial_data.get("sponsor_content_type")
        raw_obj = self.initial_data.get("sponsor_object_id")
        if raw_ct:
            if not raw_obj:
                raise serializers.ValidationError(
                    {"sponsor_object_id": "Sponsor object id is required."}
                )
            data["sponsor_content_type"] = resolve_content_type(raw_ct)
        return data


class ListUpdateSerializer(serializers.Serializer):
    """Serializer for updating a list."""

    title = serializers.CharField(max_length=100, required=False)
    body_text = serializers.CharField(required=False, allow_blank=True)
    summary = serializers.CharField(required=False, allow_blank=True)


class ListItemAnnotationSerializer(serializers.ModelSerializer):
    """Serializer for list item annotations."""

    task_id = serializers.UUIDField(source="task.id", read_only=True, allow_null=True)
    task_title = serializers.CharField(source="task.title", read_only=True, allow_null=True)
    project_id = serializers.UUIDField(source="task.project.id", read_only=True, allow_null=True)
    project_title = serializers.CharField(source="task.project.title", read_only=True, allow_null=True)
    promoted_by_username = serializers.CharField(source="promoted_by.username", read_only=True, allow_null=True)

    class Meta:
        model = ListItemAnnotation
        fields = [
            "id",
            "item_text_hash",
            "item_text_snapshot",
            "task_id",
            "task_title",
            "project_id",
            "project_title",
            "promoted_at",
            "promoted_by_username",
        ]
        read_only_fields = fields


class ListItemPromoteSerializer(serializers.Serializer):
    """Serializer for promoting a list item to a project task."""

    project_id = serializers.UUIDField()
    column_id = serializers.UUIDField(required=False, allow_null=True)
    item_text = serializers.CharField(max_length=500)
