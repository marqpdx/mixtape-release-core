from rest_framework import serializers


class AgentContextSerializer(serializers.Serializer):
    sponsor_model = serializers.CharField(required=False)
    sponsor_id = serializers.UUIDField(required=False)


class AgentParseRequestSerializer(serializers.Serializer):
    text = serializers.CharField()
    capture_mode = serializers.ChoiceField(
        choices=["typed", "voice", "imported", "pasted"],
        default="typed",
    )
    surface = serializers.ChoiceField(
        choices=["mobile", "desktop"],
        default="mobile",
    )
    initiative_id = serializers.UUIDField(required=False, allow_null=True)
    context = AgentContextSerializer(required=False)


class AgentNoteCommandSerializer(serializers.Serializer):
    initiative_id = serializers.UUIDField(required=False, allow_null=True)
    sponsor_model = serializers.CharField(required=False)
    sponsor_id = serializers.UUIDField(required=False)
    title = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField()
    capture_mode = serializers.ChoiceField(
        choices=["typed", "voice", "imported", "pasted"],
        default="typed",
    )
    origin = serializers.ChoiceField(choices=["agent", "manual"], default="agent")
    raw_input = serializers.CharField(required=False, allow_blank=True, default="")
    parsed_metadata = serializers.DictField(required=False, default=dict)


class AgentReminderCommandSerializer(serializers.Serializer):
    initiative_id = serializers.UUIDField(required=False, allow_null=True)
    sponsor_model = serializers.CharField(required=False)
    sponsor_id = serializers.UUIDField(required=False)
    title = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField()
    remind_at = serializers.DateTimeField()
    capture_mode = serializers.ChoiceField(
        choices=["typed", "voice", "imported", "pasted"],
        default="typed",
    )
    origin = serializers.ChoiceField(choices=["agent", "manual"], default="agent")
    raw_input = serializers.CharField(required=False, allow_blank=True, default="")
    parsed_metadata = serializers.DictField(required=False, default=dict)


class AgentTaskCommandSerializer(serializers.Serializer):
    initiative_id = serializers.UUIDField(required=False, allow_null=True)
    sponsor_model = serializers.CharField(required=False)
    sponsor_id = serializers.UUIDField(required=False)
    title = serializers.CharField()
    details = serializers.CharField(required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    assigned_to_id = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.ChoiceField(
        choices=["todo", "in_progress", "done", "cancelled"],
        default="todo",
    )
    capture_mode = serializers.ChoiceField(
        choices=["typed", "voice", "imported", "pasted"],
        default="typed",
    )
    origin = serializers.ChoiceField(choices=["agent", "manual"], default="agent")
    raw_input = serializers.CharField(required=False, allow_blank=True, default="")
    parsed_metadata = serializers.DictField(required=False, default=dict)


class AgentParseUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField()
    parse_route = serializers.CharField()
