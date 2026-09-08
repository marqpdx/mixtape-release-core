from django.contrib import admin

from .models import (
    ExternalConnection,
    ProvisionalThing,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
    WorkingSetMembership,
)


@admin.register(ExternalConnection)
class ExternalConnectionAdmin(admin.ModelAdmin):
    list_display = ("display_name", "provider", "group", "status", "connected_at", "created_at")
    list_filter = ("provider", "status", "group")
    search_fields = ("display_name", "provider_account_id", "credential_reference")
    exclude = ("credential_payload",)


@admin.register(SourceGrant)
class SourceGrantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "resource_kind", "connection", "initiative", "status", "created_at")
    list_filter = ("resource_kind", "status")
    search_fields = ("display_name", "resource_id")


@admin.register(SourceEvidence)
class SourceEvidenceAdmin(admin.ModelAdmin):
    list_display = ("sender_email", "provider_message_id", "source_grant", "sent_at", "body_snapshot_status")
    list_filter = ("provider", "body_snapshot_status")
    search_fields = ("sender_email", "sender_display_name_raw", "provider_message_id", "subject")


@admin.register(ProvisionalThing)
class ProvisionalThingAdmin(admin.ModelAdmin):
    list_display = ("preferred_name", "email", "possible_type", "status", "name_source", "name_confidence", "name_status")
    list_filter = ("possible_type", "status", "name_source", "name_confidence", "name_status")
    search_fields = ("preferred_name", "email", "organization_guess")


class WorkingSetMembershipInline(admin.TabularInline):
    model = WorkingSetMembership
    extra = 0


@admin.register(WorkingSet)
class WorkingSetAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "initiative", "status", "updated_at")
    list_filter = ("status", "group")
    search_fields = ("title", "purpose")
    inlines = [WorkingSetMembershipInline]


@admin.register(WorkingSetMembership)
class WorkingSetMembershipAdmin(admin.ModelAdmin):
    list_display = ("working_set", "provisional_thing", "status", "position", "created_at")
    list_filter = ("status",)
