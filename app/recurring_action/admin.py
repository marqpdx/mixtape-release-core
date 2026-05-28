from django.contrib import admin

from .models import RecurringAction


@admin.register(RecurringAction)
class RecurringActionAdmin(admin.ModelAdmin):
    list_display = ["title", "recurrence_rule", "next_due_at", "last_triggered_at", "is_active"]
    list_filter = ["recurrence_rule", "is_active"]
    search_fields = ["title", "description"]
    readonly_fields = ["last_triggered_at", "created_at", "updated_at"]
