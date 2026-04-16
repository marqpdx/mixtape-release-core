from django.contrib import admin

from .models import Group, GroupInvitation


@admin.register(Group)
class CircleAdmin(admin.ModelAdmin):
    list_display = ["title", "group_type", "is_helper_group", "created_at"]
    search_fields = ["title", "description"]
    list_filter = ["group_type", "is_helper_group"]
    readonly_fields = ["slug"]
    fieldsets = [
        (None, {"fields": ["title", "description", "group_type", "slug"]}),
        ("Helper / Beacon access", {"fields": ["is_helper_group"]}),
    ]


@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
    list_display = [
        "invited_email", "group", "invitation_status", "email_status",
        "provider_message_id", "sent_at", "last_queued_at", "invited_by",
    ]
    list_filter = ["invitation_status", "email_status", "provider", "group"]
    search_fields = ["invited_email", "group__title", "provider_message_id", "last_task_id"]
    readonly_fields = [
        "provider", "provider_message_id", "last_send_error",
        "last_task_id", "last_queued_at", "sent_at",
        "created_at", "updated_at",
    ]
    fieldsets = [
        (None, {"fields": [
            "group", "invited_by", "invited_user", "invited_email",
            "invitation_status", "email_status", "message",
        ]}),
        ("Delivery tracking", {"fields": [
            "provider", "provider_message_id", "last_task_id",
            "last_queued_at", "sent_at", "last_send_error",
        ]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
    ]
