# activity/api/serializers.py

from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from activity.models import Notification, NotificationPreference


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
            "level",
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
            return getattr(obj.action.actor, "username", getattr(obj.action.actor, "get_full_name", lambda: str(obj.action.actor))())
        return "System"

    def get_object_name(self, obj):
        if obj.action.object:
            return getattr(obj.action.object, "title", getattr(obj.action.object, "name", str(obj.action.object)))
        return ""

    def get_action_url(self, obj):
        if obj.action.metadata.get("action_url"):
            return obj.action.metadata.get("action_url", "")
        if obj.action.metadata.get("url"):
            return obj.action.metadata.get("url", "")
        # For group invitations, return the invite URL from metadata
        if obj.action.activity_code in ("group_invitation", "group.invitation"):
            return obj.action.metadata.get("invite_url", "")

        # Otherwise construct based on object type
        if obj.action.object:
            absolute_url = getattr(obj.action.object, "get_absolute_url", None)
            if callable(absolute_url):
                try:
                    return absolute_url()
                except Exception:
                    pass
            ct = ContentType.objects.get_for_model(obj.action.object)
            if ct.model == "group":
                return f"/app/groups/{obj.action.object.slug}"
            if ct.model == "writingpiece":
                sponsor = getattr(obj.action.object, "sponsor", None)
                sponsor_slug = getattr(sponsor, "slug", None)
                piece_slug = getattr(obj.action.object, "slug", None)
                if sponsor_slug and piece_slug:
                    return f"/app/groups/{sponsor_slug}/writing/{piece_slug}"
            if ct.model == "writingcomment":
                piece = getattr(obj.action.object, "piece", None)
                sponsor = getattr(piece, "sponsor", None)
                sponsor_slug = getattr(sponsor, "slug", None)
                piece_slug = getattr(piece, "slug", None)
                if sponsor_slug and piece_slug:
                    return f"/app/groups/{sponsor_slug}/writing/{piece_slug}#comment-{obj.action.object.pk}"
        return ""


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "bucket",
            "activity_code",
            "level",
        ]
