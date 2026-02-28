# spellbook/api/serializers.py

from rest_framework import serializers

from spellbook.models import SpellCorrection, SpellSuggestion, UserDictionaryEntry


class SpellCorrectionSerializer(serializers.ModelSerializer):
    """Serializer for approved spell corrections."""

    added_by_username = serializers.CharField(
        source="added_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = SpellCorrection
        fields = [
            "id",
            "wrong_word",
            "correct_word",
            "added_by_username",
            "created_at",
            "usage_count",
        ]
        read_only_fields = ["id", "added_by_username", "created_at", "usage_count"]


class SpellCorrectionCreateSerializer(serializers.Serializer):
    """Serializer for creating a new spell correction (superadmin only)."""

    wrong_word = serializers.CharField(max_length=100)
    correct_word = serializers.CharField(max_length=100)

    def validate_wrong_word(self, value):
        """Normalize to lowercase."""
        return value.lower().strip()

    def validate_correct_word(self, value):
        """Trim whitespace."""
        return value.strip()

    def validate(self, attrs):
        """Ensure wrong_word doesn't already exist."""
        if SpellCorrection.objects.filter(wrong_word=attrs["wrong_word"]).exists():
            raise serializers.ValidationError(
                {"wrong_word": "A correction for this word already exists."}
            )
        return attrs


class SpellSuggestionSerializer(serializers.ModelSerializer):
    """Serializer for spell suggestions."""

    suggested_by_username = serializers.CharField(
        source="suggested_by.username", read_only=True
    )
    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = SpellSuggestion
        fields = [
            "id",
            "wrong_word",
            "correct_word",
            "suggested_by_username",
            "created_at",
            "status",
            "reviewed_by_username",
            "reviewed_at",
            "review_note",
        ]
        read_only_fields = [
            "id",
            "suggested_by_username",
            "created_at",
            "status",
            "reviewed_by_username",
            "reviewed_at",
            "review_note",
        ]


class SpellSuggestionCreateSerializer(serializers.Serializer):
    """Serializer for submitting a new spell suggestion."""

    wrong_word = serializers.CharField(max_length=100)
    correct_word = serializers.CharField(max_length=100)

    def validate_wrong_word(self, value):
        """Normalize to lowercase."""
        return value.lower().strip()

    def validate_correct_word(self, value):
        """Trim whitespace."""
        return value.strip()

    def validate(self, attrs):
        """Check if correction already exists."""
        if SpellCorrection.objects.filter(wrong_word=attrs["wrong_word"]).exists():
            raise serializers.ValidationError(
                {"wrong_word": "A correction for this word already exists."}
            )
        return attrs


class UserDictionaryEntryCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=UserDictionaryEntry.Kind.choices)
    token = serializers.CharField(max_length=100)
    display = serializers.CharField(max_length=100, required=False, allow_blank=True)
    replacement = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_token(self, value):
        return value.lower().strip()

    def validate_replacement(self, value):
        return value.strip()

    def validate(self, attrs):
        kind = attrs.get("kind")
        replacement = attrs.get("replacement", "")
        if kind == UserDictionaryEntry.Kind.REPLACE and not replacement:
            raise serializers.ValidationError({"replacement": "Replacement is required for replace entries."})
        return attrs
