# spellbook/admin.py

from django.contrib import admin

from spellbook.models import SpellCorrection, SpellSuggestion


@admin.register(SpellCorrection)
class SpellCorrectionAdmin(admin.ModelAdmin):
    list_display = ["wrong_word", "correct_word", "added_by", "usage_count", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["wrong_word", "correct_word"]
    readonly_fields = ["id", "created_at", "usage_count"]
    ordering = ["wrong_word"]


@admin.register(SpellSuggestion)
class SpellSuggestionAdmin(admin.ModelAdmin):
    list_display = ["wrong_word", "correct_word", "suggested_by", "status", "created_at"]
    list_filter = ["status", "created_at"]
    search_fields = ["wrong_word", "correct_word", "suggested_by__username"]
    readonly_fields = ["id", "created_at", "reviewed_at"]
    ordering = ["-created_at"]

    actions = ["approve_suggestions", "reject_suggestions"]

    def approve_suggestions(self, request, queryset):
        """Bulk approve pending suggestions."""
        from django.utils import timezone

        approved = 0
        for suggestion in queryset.filter(status="pending"):
            if not SpellCorrection.objects.filter(wrong_word=suggestion.wrong_word).exists():
                SpellCorrection.objects.create(
                    wrong_word=suggestion.wrong_word,
                    correct_word=suggestion.correct_word,
                    added_by=suggestion.suggested_by,
                )
                suggestion.status = "approved"
                suggestion.reviewed_by = request.user
                suggestion.reviewed_at = timezone.now()
                suggestion.save()
                approved += 1

        self.message_user(request, f"{approved} suggestions approved.")

    approve_suggestions.short_description = "Approve selected suggestions"

    def reject_suggestions(self, request, queryset):
        """Bulk reject pending suggestions."""
        from django.utils import timezone

        count = queryset.filter(status="pending").update(
            status="rejected",
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{count} suggestions rejected.")

    reject_suggestions.short_description = "Reject selected suggestions"
