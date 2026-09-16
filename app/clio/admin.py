from django.contrib import admin

from .models import ClioState, KeeperRegistration


@admin.register(ClioState)
class ClioStateAdmin(admin.ModelAdmin):
    list_display = ["profile", "last_surfaced_at", "dismiss_mode", "remind_later_at"]
    list_filter = ["dismiss_mode"]
    raw_id_fields = ["profile"]


@admin.register(KeeperRegistration)
class KeeperRegistrationAdmin(admin.ModelAdmin):
    list_display = ["keeper_id", "keeper_name", "owner_subsystem", "status", "finding_cadence", "registered_at"]
    list_filter = ["status", "finding_cadence", "owner_subsystem"]
    search_fields = ["keeper_id", "keeper_name", "owner_subsystem"]
    readonly_fields = ["id", "registered_at", "archived_at"]
