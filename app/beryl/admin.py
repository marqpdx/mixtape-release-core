from django.contrib import admin

from .models import BerylState


@admin.register(BerylState)
class BerylStateAdmin(admin.ModelAdmin):
    list_display = ["profile", "last_surfaced_at", "dismiss_mode", "remind_later_at"]
    list_filter = ["dismiss_mode"]
    raw_id_fields = ["profile"]
