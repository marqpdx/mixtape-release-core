from rest_framework import serializers

from surfaces.services.argus_blocks import read_audit_block


class RunSeriesSpanSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["days", "runs"])
    value = serializers.IntegerField(min_value=1)


class PerTurnCapsSerializer(serializers.Serializer):
    max_tokens = serializers.IntegerField(min_value=0)
    max_turns = serializers.IntegerField(min_value=0)
    max_wall_clock_seconds = serializers.IntegerField(min_value=0)


class CreateRunSeriesSerializer(serializers.Serializer):
    block_slug = serializers.SlugField()
    cadence_hours = serializers.IntegerField(min_value=1)
    span = RunSeriesSpanSerializer()
    per_turn_caps = PerTurnCapsSerializer()

    def validate_block_slug(self, value):
        block, reason = read_audit_block(value)
        if block is None:
            if reason.startswith("No audit block named"):
                raise serializers.ValidationError(f"Unknown block '{value}'.")
            # Registry unavailable (e.g. PUDDLEJUMP_PATH unset) -- can't cross-check.
            return value
        if block.block_state != "ready":
            raise serializers.ValidationError(
                f"Block '{value}' is not ready (state: {block.block_state})."
            )
        return value

    def validate(self, data):
        span = data["span"]
        if span["kind"] == "runs":
            total_hours = data["cadence_hours"] * span["value"]
            if total_hours > 7 * 24:
                raise serializers.ValidationError(
                    {"span": "A run series lasts at most seven days (D9): "
                             "cadence_hours x the run count must not exceed 168 hours."}
                )
        return data
