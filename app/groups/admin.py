from django.contrib import admin
from django.utils.text import slugify

from .models import Group, GroupInvitation


@admin.register(Group)
class CircleAdmin(admin.ModelAdmin):
    list_display = ["title", "slug", "group_type", "is_helper_group", "created_at"]
    search_fields = ["title", "description", "slug"]
    list_filter = ["group_type", "is_helper_group"]
    readonly_fields = ["slug", "slug_history"]
    fieldsets = [
        (None, {"fields": ["title", "description", "group_type", "slug", "slug_history"]}),
        ("Helper / Beacon access", {"fields": ["is_helper_group"]}),
    ]

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        if change and "title" in form.changed_data:
            old_slug = obj.slug
            base = slugify(obj.title)
            if base:
                new_slug = obj._build_unique_slug(base)
                if new_slug != old_slug:
                    if old_slug and old_slug not in obj.slug_history:
                        obj.slug_history.append(old_slug)
                    obj.slug = new_slug
        super().save_model(request, obj, form, change)


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
