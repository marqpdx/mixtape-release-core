from django.contrib import admin

from .models import Group, GroupInvitation


@admin.register(Group)
class CircleAdmin(admin.ModelAdmin):
    list_display = ["title", "group_type", "is_helper_group", "created_at"]
    search_fields = ["title", "description"]
    list_filter = ["group_type", "is_helper_group"]
    fieldsets = [
        (None, {"fields": ["title", "description", "group_type", "slug"]}),
        ("Helper / Beacon access", {"fields": ["is_helper_group"]}),
    ]


@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
    list_display = ["invited_by", "invited_user", "invited_email", "group"]
    search_fields = ["invited_by", "invited_user", "invited_email", "group"]
