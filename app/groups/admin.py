from django.contrib import admin
from django.utils.text import slugify

from .models import Group, GroupContext, GroupInvitation


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


@admin.register(GroupContext)
class GroupContextAdmin(admin.ModelAdmin):
    list_display = ["group", "context_health_score", "last_prompted_at", "updated_at"]
    search_fields = ["group__title", "founding_story", "voice_description"]
    readonly_fields = ["context_health_score", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["group"]}),
        ("Context fields", {"fields": ["founding_story", "non_negotiables", "voice_description", "outward_feel"]}),
        ("Health", {"fields": ["context_health_score", "last_prompted_at"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
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


from .models.group_public_config import GroupPublicConfig


@admin.register(GroupPublicConfig)
class GroupPublicConfigAdmin(admin.ModelAdmin):
    list_display = ["group", "is_active", "generation_status", "hero_headline", "subscription_list", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["group__title", "group__slug", "hero_headline"]
    raw_id_fields = ["group", "featured_collection", "subscription_list"]
    fieldsets = [
        (None, {"fields": ["group", "is_active"]}),
        ("Hero", {"fields": [
            "hero_eyebrow", "hero_headline", "hero_body",
            "hero_primary_cta_label", "hero_primary_cta_action",
            "hero_secondary_cta_label", "hero_secondary_cta_action",
        ]}),
        ("Featured Content", {"fields": [
            "featured_collection", "featured_item_ids",
            "featured_content_type", "featured_layout",
        ]}),
        ("About", {"fields": ["about_text", "about_descriptors"]}),
        ("Engagement", {"fields": [
            "engagement_text", "engagement_capability_pills",
            "engagement_cta_label", "engagement_cta_action",
        ]}),
        ("Subscription", {"fields": ["subscription_list"]}),
        ("AI Generation", {"fields": ["generation_status", "rows", "generation_metadata"], "classes": ["collapse"]}),
        ("Timestamps", {"fields": ["created_at", "updated_at"]}),
    ]
    readonly_fields = ["rows", "generation_metadata", "created_at", "updated_at"]
