from django.contrib import admin

from .models import LanternmailList, LanternmailPost, WelcomeEmailDraft


@admin.register(LanternmailList)
class LanternmailListAdmin(admin.ModelAdmin):
    list_display = ["display_name", "group", "listmonk_id", "is_active", "created_at"]
    list_filter = ["is_active", "group"]
    search_fields = ["display_name", "listmonk_name", "group__title"]


@admin.register(LanternmailPost)
class LanternmailPostAdmin(admin.ModelAdmin):
    list_display = ["title", "group", "status", "audience_kind", "sent_at", "created_by"]
    list_filter = ["status", "audience_kind"]
    search_fields = ["title", "subject"]
    readonly_fields = ["created_by", "sent_at", "listmonk_campaign_id", "created_at", "updated_at"]


@admin.register(WelcomeEmailDraft)
class WelcomeEmailDraftAdmin(admin.ModelAdmin):
    list_display = ["to_email", "to_name", "group", "prospect", "status", "created_at", "sent_at"]
    list_filter = ["status", "group"]
    search_fields = ["to_email", "to_name", "prospect__name", "group__title"]
    readonly_fields = ["prospect", "group", "created_at", "updated_at", "sent_at"]
    fieldsets = [
        (None, {"fields": ["prospect", "group", "status", "sent_at"]}),
        ("Recipient", {"fields": ["to_name", "to_email"]}),
        ("Content", {"fields": ["subject", "body"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
    ]
