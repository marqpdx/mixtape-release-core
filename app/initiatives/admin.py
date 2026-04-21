from django.contrib import admin

from .models import Artifact, Initiative, LinkedOutput, Note, Reminder, Session, Task


@admin.register(Initiative)
class InitiativeAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "created_by", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "direction")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("initiative", "intent", "capture_mode", "distillation_state", "created_by", "started_at", "ended_at")
    list_filter = ("intent", "capture_mode", "distillation_state")
    readonly_fields = ("id", "started_at")


@admin.register(Artifact)
class ArtifactAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "initiative", "session", "puddlejump_routed", "quality_scan_state", "created_at")
    list_filter = ("kind", "puddlejump_routed", "quality_scan_state")
    search_fields = ("title", "body")
    readonly_fields = ("id", "created_at")


@admin.register(LinkedOutput)
class LinkedOutputAdmin(admin.ModelAdmin):
    list_display = ("initiative", "output_content_type", "output_object_id", "created_at")
    readonly_fields = ("id", "created_at")


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("title", "initiative", "capture_mode", "origin", "created_by", "created_at")
    list_filter = ("capture_mode", "origin")
    search_fields = ("title", "body", "raw_input")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ("title", "initiative", "status", "remind_at", "capture_mode", "created_by")
    list_filter = ("status", "capture_mode", "origin")
    search_fields = ("title", "body", "raw_input")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "initiative", "status", "assigned_to", "due_at", "created_by", "created_at")
    list_filter = ("status", "capture_mode", "origin")
    search_fields = ("title", "details", "raw_input")
    readonly_fields = ("id", "created_at", "updated_at")
