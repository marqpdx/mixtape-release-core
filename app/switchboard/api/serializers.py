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


class AgentAddCommandSerializer(serializers.Serializer):
    list_title = serializers.CharField()
    items = serializers.ListField(child=serializers.CharField(), min_length=1)
    create_if_missing = serializers.BooleanField(default=True)
    surface = serializers.ChoiceField(choices=["mobile", "desktop", "atrium"], default="mobile")


class AgentFindCommandSerializer(serializers.Serializer):
    query = serializers.CharField()
    library_id = serializers.UUIDField(required=False, allow_null=True)
    limit = serializers.IntegerField(default=8, min_value=1, max_value=20)
    score_threshold = serializers.FloatField(default=0.0)
    surface = serializers.ChoiceField(choices=["mobile", "desktop", "atrium"], default="desktop")
    group_slug = serializers.CharField(required=False, allow_blank=True, default="")


class AgentResearchCommandSerializer(serializers.Serializer):
    query = serializers.CharField()
    max_sources = serializers.IntegerField(default=3, min_value=1, max_value=5)
    surface = serializers.ChoiceField(choices=["mobile", "desktop"], default="desktop")


class AgentPatternCommandSerializer(serializers.Serializer):
    query = serializers.CharField()
    library_id = serializers.UUIDField(required=False, allow_null=True)
    max_sources = serializers.IntegerField(default=15, min_value=5, max_value=30)
    surface = serializers.ChoiceField(choices=["mobile", "desktop"], default="desktop")


class AgentSynthesizeCommandSerializer(serializers.Serializer):
    query = serializers.CharField()
    library_id = serializers.UUIDField(required=False, allow_null=True)
    max_sources = serializers.IntegerField(default=15, min_value=5, max_value=30)
    surface = serializers.ChoiceField(choices=["mobile", "desktop"], default="desktop")


class AgentSynthesizeNarrativeCommandSerializer(serializers.Serializer):
    action_run_id = serializers.UUIDField()


class AgentSynopsisLinkedInCommandSerializer(serializers.Serializer):
    piece_id = serializers.UUIDField()
    surface = serializers.ChoiceField(choices=["console", "puddlejump", "writing"], default="writing")


class SourceGrantLatestMessagesSerializer(serializers.Serializer):
    resource_kind = serializers.CharField(max_length=64)
    resource_id = serializers.CharField(max_length=255)
    limit = serializers.IntegerField(default=5, min_value=1, max_value=25)


class AgentParseUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField()
    parse_route = serializers.CharField()


class GroupSearchSerializer(serializers.Serializer):
    group_id = serializers.UUIDField()
    query = serializers.CharField(max_length=500)
    max_results = serializers.IntegerField(default=5, min_value=1, max_value=10)
