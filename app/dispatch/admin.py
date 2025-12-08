from django.contrib import admin

from dispatch.models import Post

from .models import DispatchContent, DispatchContentVersion, DispatchEditSession, DispatchCollaborator
# Register your models here.


admin.site.register(Post)


@admin.register(DispatchContent)
class DispatchContentAdmin(admin.ModelAdmin):
    list_display = ("yjs_document_id", "get_collaborator_count", "is_archived", "updated_at")
    list_filter = ("is_archived",)
    readonly_fields = ("yjs_document_id", "yjs_state_updated_at", "snapshot_updated_at", "created_at", "updated_at")

    def get_collaborator_count(self, obj):
        return obj.collaborators.count()
    get_collaborator_count.short_description = "Collaborators"


@admin.register(DispatchCollaborator)
class DispatchCollaboratorAdmin(admin.ModelAdmin):
    list_display = ("user", "content", "role", "invited_by", "created_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")

@admin.register(DispatchContentVersion)
class DispatchContentVersionAdmin(admin.ModelAdmin):
    list_display = ("content", "created_by", "created_at", "is_manual")
    readonly_fields = ("content_snapshot",)

@admin.register(DispatchEditSession)
class DispatchEditSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "content", "started_at", "last_active_at", "is_active")
    list_filter = ("is_active",)
