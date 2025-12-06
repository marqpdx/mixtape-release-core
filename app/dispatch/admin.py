from django.contrib import admin

from dispatch.models import Post

from .models import DispatchDocument, DispatchDocumentVersion, DispatchEditSession
# Register your models here.


admin.site.register(Post)


@admin.register(DispatchDocument)
class DispatchDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "submitted_by", "sponsor_display", "is_published", "updated_at")
    search_fields = ("title", "description", "slug")
    list_filter = ("is_archived",)
    filter_horizontal = ("collaborators",)
    readonly_fields = ("sponsor_display", "author_display")

@admin.register(DispatchDocumentVersion)
class DispatchDocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "created_by", "created_at", "is_manual")
    readonly_fields = ("content_snapshot",)

@admin.register(DispatchEditSession)
class DispatchEditSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "document", "started_at", "last_active_at", "is_active")
    list_filter = ("is_active",)
