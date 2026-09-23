from django.contrib import admin

from .models import (
    ExternalConnection,
    OpportunityApplicationDraft,
    OpportunityProfile,
    ProvisionalData,
    ProvisionalDataMembership,
    SourceEvidence,
    SourceGrant,
    WorkingSet,
)


@admin.register(ExternalConnection)
class ExternalConnectionAdmin(admin.ModelAdmin):
    list_display = ("display_name", "provider", "group", "owner", "status", "connected_at", "created_at")
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


class ProvisionalDataMembershipInline(admin.TabularInline):
    model = ProvisionalDataMembership
    extra = 0
    fields = ("provisional_data", "status", "position", "note")


@admin.register(WorkingSet)
class WorkingSetAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "owner_user", "source", "initiative", "status", "updated_at")
    list_filter = ("status", "source", "group")
    search_fields = ("title", "purpose")
    inlines = [ProvisionalDataMembershipInline]


@admin.register(ProvisionalData)
class ProvisionalDataAdmin(admin.ModelAdmin):
    list_display = ("__str__", "kind", "source_type", "state", "freshness", "confidence", "owner_user", "observed_at", "created_at")
    list_filter = ("kind", "source_type", "state", "freshness")
    search_fields = ("source_external_id", "source_locator", "normalized_payload")
    readonly_fields = ("id", "promoted_object", "created_at", "updated_at")
    fieldsets = (
        (None, {
            "fields": ("id", "kind", "source_type", "source_locator", "source_external_id", "state"),
        }),
        ("Temporal", {
            "fields": ("captured_at", "observed_at"),
        }),
        ("Evaluation", {
            "fields": ("confidence", "freshness"),
        }),
        ("Payload", {
            "fields": ("raw_payload", "normalized_payload"),
            "classes": ("collapse",),
        }),
        ("Provenance", {
            "fields": ("provenance", "source_evidence"),
            "classes": ("collapse",),
        }),
        ("Ownership & Promotion", {
            "fields": ("owner_user", "promoted_content_type", "promoted_object_id", "promoted_object"),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )


@admin.register(ProvisionalDataMembership)
class ProvisionalDataMembershipAdmin(admin.ModelAdmin):
    list_display = ("working_set", "provisional_data", "status", "position", "created_at")
    list_filter = ("status",)


@admin.register(OpportunityProfile)
class OpportunityProfileAdmin(admin.ModelAdmin):
    list_display = ("owner_user", "name", "version", "is_current", "freshness_hours", "updated_at")
    list_filter = ("is_current", "freshness_hours")
    search_fields = ("owner_user__username", "owner_user__email", "name", "resume_label")


@admin.register(OpportunityApplicationDraft)
class OpportunityApplicationDraftAdmin(admin.ModelAdmin):
    list_display = ("opportunity", "owner_user", "status", "generated_by", "updated_at")
    list_filter = ("status", "generated_by")
    search_fields = (
        "owner_user__username",
        "owner_user__email",
        "recipient_name",
        "recipient_email",
        "opportunity__normalized_payload",
    )
    readonly_fields = ("generation_context", "generated_at", "created_at", "updated_at")
