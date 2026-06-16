# drop/api/serializers.py
from rest_framework import serializers

from drop.models import Drop, DropWeight


class DropSerializer(serializers.ModelSerializer):
    created_by_username = serializers.SerializerMethodField()

    class Meta:
        model = Drop
        fields = [
            "id",
            "handle",
            "content",
            "weight",
            "created_by_username",
            "created_at",
            "expires_at",
            "is_archived",
            "event_date",
            "related_handle",
            "almanac_event_id",
        ]
        read_only_fields = ["id", "created_at", "created_by_username"]

    def get_created_by_username(self, obj):
        if obj.created_by:
            return obj.created_by.username
        return None


class DropCreateSerializer(serializers.Serializer):
    handle = serializers.SlugField(max_length=100)
    content = serializers.CharField()
    weight = serializers.ChoiceField(
        choices=[w.value for w in DropWeight],
        default=DropWeight.STANDARD,
    )
    event_date = serializers.DateField(required=False, allow_null=True)
    related_handle = serializers.CharField(max_length=200, required=False, allow_blank=True)
    almanac_event_id = serializers.UUIDField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
