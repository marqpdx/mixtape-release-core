# activity/api/serializers.py

from rest_framework import serializers
from activity.models import Notification
from django.contrib.contenttypes.models import ContentType

class NotificationSerializer(serializers.ModelSerializer):
    action_code = serializers.CharField(source="action.activity_code", read_only=True)
    action_channel = serializers.CharField(source="action.channel", read_only=True)
    actor_name = serializers.SerializerMethodField()
    object_name = serializers.SerializerMethodField()
    action_url = serializers.SerializerMethodField()
    verb = serializers.CharField(source="action.verb", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "bucket",
            "priority",
            "aggregate_count",
            "last_occurred_at",
            "is_read",
            "is_seen",
            "dedupe_key",
            "aggregate_key",
            "action_code",
            "action_channel",
            "actor_name",
            "object_name",
            "action_url",
            "verb",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.action.actor:
            return getattr(obj.action.actor, 'username', getattr(obj.action.actor, 'get_full_name', lambda: str(obj.action.actor))())
        return 'System'

    def get_object_name(self, obj):
        if obj.action.object:
            return getattr(obj.action.object, 'title', getattr(obj.action.object, 'name', str(obj.action.object)))
        return ''

    def get_action_url(self, obj):
        # For group invitations, return the invite URL from metadata
        if obj.action.activity_code == 'group_invitation':
            return obj.action.metadata.get('invite_url', '')

        # Otherwise construct based on object type
        if obj.action.object:
            ct = ContentType.objects.get_for_model(obj.action.object)
            if ct.model == 'group':
                return f"/groups/{obj.action.object.slug}"
        return ''