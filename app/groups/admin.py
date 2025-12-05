from django.contrib import admin

from .models import Group, GroupInvitation


@admin.register(Group)
class CircleAdmin(admin.ModelAdmin):
    list_display = ["title", "description", "created_at", "group_type"]
    search_fields = ["title", "description", "created_at", "group_type"]


@admin.register(GroupInvitation)
class GroupInvitationAdmin(admin.ModelAdmin):
    list_display = ["invited_by", "invited_user", "invited_email", "group"]
    search_fields = ["invited_by", "invited_user", "invited_email", "group"]
