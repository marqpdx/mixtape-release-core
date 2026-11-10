from rest_framework import serializers


class RunSeriesSpanSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["days", "runs"])
    value = serializers.IntegerField(min_value=1)


class CreateRunSeriesSerializer(serializers.Serializer):
    block_slug = serializers.SlugField()
    cadence_hours = serializers.IntegerField(min_value=1)
    span = RunSeriesSpanSerializer()
    per_turn_caps = serializers.DictField(required=False, default=dict)
