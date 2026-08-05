from django.contrib import admin

from .models import (
    BusinessProspect,
    OnboardingQuestion,
    ProspectInsight,
    ProspectIntakeSession,
    ProspectNote,
    ProspectQuestion,
    ProspectQuestionOnboardingMap,
    ProspectResponse,
)


@admin.register(BusinessProspect)
class BusinessProspectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "primary_contact_email", "converted_to_group", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "primary_contact_email")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("sponsor_content_type",)
    readonly_fields = ("org_description", "knowledge_goal")

    def has_module_perms(self, request, app_label=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ProspectIntakeSession)
class ProspectIntakeSessionAdmin(admin.ModelAdmin):
    list_display = ("prospect", "mode", "status", "submitted_at")
    list_filter = ("status", "mode")
    raw_id_fields = ("prospect",)
    readonly_fields = ("resume_token",)


@admin.register(ProspectQuestion)
class ProspectQuestionAdmin(admin.ModelAdmin):
    list_display = ("order_index", "prompt", "is_active", "question_kind")
    list_display_links = ("prompt",)
    list_editable = ("order_index", "is_active")


@admin.register(ProspectResponse)
class ProspectResponseAdmin(admin.ModelAdmin):
    list_display = ("intake_session", "question", "kind", "processing_status", "created_at")
    raw_id_fields = ("intake_session", "question")


@admin.register(ProspectInsight)
class ProspectInsightAdmin(admin.ModelAdmin):
    list_display = ("prospect", "kind", "source", "title", "created_at")
    list_filter = ("kind", "source")


@admin.register(ProspectNote)
class ProspectNoteAdmin(admin.ModelAdmin):
    list_display = ("prospect", "created_by", "created_at")
    raw_id_fields = ("prospect",)


@admin.register(OnboardingQuestion)
class OnboardingQuestionAdmin(admin.ModelAdmin):
    list_display = ("category", "order", "text_preview", "triggers_persona_creation", "is_active")
    list_filter = ("category", "is_active", "triggers_persona_creation")
    list_editable = ("order", "is_active")

    def text_preview(self, obj):
        return obj.text[:80]
    text_preview.short_description = "text"


@admin.register(ProspectQuestionOnboardingMap)
class ProspectQuestionOnboardingMapAdmin(admin.ModelAdmin):
    list_display = ("prospect_question", "onboarding_question")
    raw_id_fields = ("prospect_question", "onboarding_question")
