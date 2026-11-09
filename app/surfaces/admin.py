from django.contrib import admin

from .models import SurfaceProfile


@admin.register(SurfaceProfile)
class SurfaceProfileAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "kind", "agent_host", "who_may_enter", "write_grant", "consent_rule"]
    list_filter = ["kind", "agent_host", "write_grant"]
    search_fields = ["slug", "name"]
    readonly_fields = ["created_at", "updated_at"]
