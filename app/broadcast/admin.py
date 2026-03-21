# broadcast/admin.py
from django.contrib import admin

from .models import BroadcastAudience, BroadcastDelivery, GroupBroadcast, UserBroadcastPreferences


class BroadcastAudienceInline(admin.TabularInline):
    model = BroadcastAudience
    extra = 0


class BroadcastDeliveryInline(admin.TabularInline):
    model = BroadcastDelivery
    extra = 0
    readonly_fields = ("user", "channel", "status", "sent_at", "error_message")


@admin.register(GroupBroadcast)
class GroupBroadcastAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "created_by", "priority", "status", "scheduled_at", "sent_at", "created_at")
    list_filter = ("status", "priority", "channels")
    search_fields = ("title", "body", "group__title", "created_by__username")
    readonly_fields = ("sent_at", "created_at", "updated_at")
    inlines = [BroadcastAudienceInline, BroadcastDeliveryInline]


@admin.register(UserBroadcastPreferences)
class UserBroadcastPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "allow_in_app", "allow_email", "allow_sms")
    list_filter = ("allow_in_app", "allow_email", "allow_sms")
    search_fields = ("user__username", "group__title")
