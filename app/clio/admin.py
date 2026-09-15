from django.contrib import admin

from .models import ClioState


@admin.register(ClioState)
class ClioStateAdmin(admin.ModelAdmin):
    list_display = ["profile", "last_surfaced_at", "dismiss_mode", "remind_later_at"]
    list_filter = ["dismiss_mode"]
    raw_id_fields = ["profile"]
