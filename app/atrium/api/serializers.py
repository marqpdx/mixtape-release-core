# atrium/api/serializers.py

from rest_framework import serializers

from atrium.models import AtriumSession


class AtriumSessionListSerializer(serializers.ModelSerializer):
    entry_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AtriumSession
        fields = [
            "id",
            "title",
            "session_context",
            "status",
            "last_activity_at",
            "entry_count",
            "created_at",
            "updated_at",
        ]
