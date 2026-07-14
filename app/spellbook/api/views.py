# spellbook/api/views.py

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from spellbook.api.serializers import (
    SpellCorrectionCreateSerializer,
    SpellCorrectionSerializer,
    SpellSuggestionCreateSerializer,
    SpellSuggestionSerializer,
    UserDictionaryEntryCreateSerializer,
)
from spellbook.models import SpellCorrection, SpellSuggestion, UserDictionaryEntry


class IsSuperUser(permissions.BasePermission):
    """Only allow superusers."""

    def has_permission(self, request, view):
        return request.user and request.user.is_superuser


class SpellCorrectionListView(APIView):
    """
    GET /api/spellbook/ - List all approved corrections (any authenticated user)
    POST /api/spellbook/ - Add a new correction (superadmin only)
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List all approved spell corrections."""
        corrections = SpellCorrection.objects.all()
        return Response(SpellCorrectionSerializer(corrections, many=True).data)

    def post(self, request):
        """Add a new spell correction (superadmin only)."""
        if not request.user.is_superuser:
            return Response(
                {"detail": "Only superadmins can add corrections directly."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SpellCorrectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        correction = SpellCorrection.objects.create(
            wrong_word=serializer.validated_data["wrong_word"],
            correct_word=serializer.validated_data["correct_word"],
            added_by=request.user,
        )

        return Response(
            SpellCorrectionSerializer(correction).data,
            status=status.HTTP_201_CREATED,
        )


class SpellCorrectionDetailView(APIView):
    """
    DELETE /api/spellbook/<id>/ - Remove a correction (superadmin only)
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def delete(self, request, correction_id):
        """Delete a spell correction."""
        correction = get_object_or_404(SpellCorrection, id=correction_id)
        correction.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SpellCorrectionUsageView(APIView):
    """
    POST /api/spellbook/<id>/record-usage/ - Increment usage count
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, correction_id):
        """Record that a correction was used."""
        correction = get_object_or_404(SpellCorrection, id=correction_id)
        correction.usage_count += 1
        correction.save(update_fields=["usage_count"])
        return Response({"usage_count": correction.usage_count})


class SpellSuggestionListView(APIView):
    """
    GET /api/spellbook/suggestions/ - List suggestions (superadmin: all pending, user: own)
    POST /api/spellbook/suggestions/ - Submit a new suggestion (any authenticated user)
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List spell suggestions."""
        if request.user.is_superuser:
            # Superadmins see all pending suggestions
            status_filter = request.query_params.get("status", "pending")
            suggestions = SpellSuggestion.objects.filter(status=status_filter)
        else:
            # Regular users see only their own suggestions
            suggestions = SpellSuggestion.objects.filter(suggested_by=request.user)

        return Response(SpellSuggestionSerializer(suggestions, many=True).data)

    def post(self, request):
        """Submit a new spell suggestion."""
        serializer = SpellSuggestionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        suggestion = SpellSuggestion.objects.create(
            wrong_word=serializer.validated_data["wrong_word"],
            correct_word=serializer.validated_data["correct_word"],
            suggested_by=request.user,
        )

        return Response(
            SpellSuggestionSerializer(suggestion).data,
            status=status.HTTP_201_CREATED,
        )


class SpellSuggestionApproveView(APIView):
    """
    POST /api/spellbook/suggestions/<id>/approve/ - Approve a suggestion (superadmin only)
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def post(self, request, suggestion_id):
        """Approve a spell suggestion and create a correction."""
        suggestion = get_object_or_404(
            SpellSuggestion, id=suggestion_id, status="pending"
        )

        # Check if correction already exists (might have been added separately)
        if SpellCorrection.objects.filter(wrong_word=suggestion.wrong_word).exists():
            # Mark as rejected since it's a duplicate
            suggestion.status = "rejected"
            suggestion.reviewed_by = request.user
            suggestion.reviewed_at = timezone.now()
            suggestion.review_note = "A correction for this word already exists."
            suggestion.save()
            return Response(
                {"detail": "A correction for this word already exists."},
                status=status.HTTP_409_CONFLICT,
            )

        # Create the correction
        correction = SpellCorrection.objects.create(
            wrong_word=suggestion.wrong_word,
            correct_word=suggestion.correct_word,
            added_by=suggestion.suggested_by,  # Credit the suggester
        )

        # Mark suggestion as approved
        suggestion.status = "approved"
        suggestion.reviewed_by = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.save()

        return Response(
            {
                "suggestion": SpellSuggestionSerializer(suggestion).data,
                "correction": SpellCorrectionSerializer(correction).data,
            }
        )


class SpellSuggestionRejectView(APIView):
    """
    POST /api/spellbook/suggestions/<id>/reject/ - Reject a suggestion (superadmin only)
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def post(self, request, suggestion_id):
        """Reject a spell suggestion."""
        suggestion = get_object_or_404(
            SpellSuggestion, id=suggestion_id, status="pending"
        )

        suggestion.status = "rejected"
        suggestion.reviewed_by = request.user
        suggestion.reviewed_at = timezone.now()
        suggestion.review_note = request.data.get("note", "")
        suggestion.save()

        return Response(SpellSuggestionSerializer(suggestion).data)


class UserDictionaryView(APIView):
    """
    GET /api/spellbook/dictionary - Get effective user dictionary.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = list(UserDictionaryEntry.objects.filter(owner_user=request.user, is_active=True))
        ignores = sorted(e.token for e in qs if e.kind == UserDictionaryEntry.Kind.IGNORE)
        replacements = {
            e.token: e.replacement
            for e in qs
            if e.kind == UserDictionaryEntry.Kind.REPLACE and e.replacement
        }
        entries = [
            {
                "id": str(e.id),
                "kind": e.kind,
                "token": e.token,
                "display": e.display or e.token,
                "replacement": e.replacement,
            }
            for e in qs
        ]
        return Response({"ignores": ignores, "replacements": replacements, "entries": entries})


class UserDictionaryEntryListCreateView(APIView):
    """
    POST /api/spellbook/dictionary/entries - Upsert a user dictionary entry.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = UserDictionaryEntryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        kind = serializer.validated_data["kind"]
        token = serializer.validated_data["token"]
        display = serializer.validated_data.get("display") or token
        replacement = serializer.validated_data.get("replacement", "")

        entry, _ = UserDictionaryEntry.objects.update_or_create(
            owner_user=request.user,
            kind=kind,
            token=token,
            defaults={
                "display": display,
                "replacement": replacement if kind == UserDictionaryEntry.Kind.REPLACE else "",
                "created_by": request.user,
                "is_active": True,
            },
        )

        return Response(
            {
                "id": str(entry.id),
                "kind": entry.kind,
                "token": entry.token,
                "display": entry.display,
                "replacement": entry.replacement,
                "is_active": entry.is_active,
            },
            status=status.HTTP_201_CREATED,
        )


class UserDictionaryEntryDetailView(APIView):
    """
    DELETE /api/spellbook/dictionary/entries/<id>/ - Delete a user dictionary entry.
    """

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, entry_id):
        entry = get_object_or_404(UserDictionaryEntry, id=entry_id, owner_user=request.user)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
