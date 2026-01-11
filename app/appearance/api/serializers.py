# appearance/api/serializers.py

from rest_framework import serializers

from appearance.models import GroupThemeSettings


class GroupThemeSettingsSerializer(serializers.ModelSerializer):
    group_id = serializers.UUIDField(source="group.id", read_only=True)
    group_slug = serializers.CharField(source="group.slug", read_only=True)

    class Meta:
        model = GroupThemeSettings
        fields = [
            "group_id",
            "group_slug",
            "hidden_theme_ids",
            "group_themes",
        ]


class GroupThemeSettingsUpdateSerializer(serializers.Serializer):
    hidden_theme_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
    )
    group_themes = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
    )
