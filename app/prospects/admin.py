from django.contrib import admin

from .models import (
    BusinessProspect,
    ProspectInsight,
    ProspectIntakeSession,
    ProspectNote,
    ProspectQuestion,
    ProspectResponse,
)


@admin.register(BusinessProspect)
class BusinessProspectAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "primary_contact_email", "sponsor_content_type", "created_at")
    list_filter = ("status", "sponsor_content_type")
    search_fields = ("name", "primary_contact_email")
    prepopulated_fields = {"slug": ("name",)}
    raw_id_fields = ("sponsor_content_type",)


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
