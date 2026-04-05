from django.contrib import admin

from writing.models import Leaf, LeafComment, WorkingDocument, WritingPiece, WritingSeries, WritingSynopsis


@admin.register(WorkingDocument)
class WorkingDocumentAdmin(admin.ModelAdmin):
    list_display = ["id", "piece", "user", "last_saved_at"]


@admin.register(WritingSeries)
class WritingSeriesAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "slug", "phase_num", "group"]
    list_filter = ["group"]
    search_fields = ["title", "slug"]
    ordering = ["group", "phase_num"]


@admin.register(WritingPiece)
class WritingPieceAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "status", "writing_kind", "author", "series"]


@admin.register(WritingSynopsis)
class WritingSynopsisAdmin(admin.ModelAdmin):
    list_display = ["id", "piece", "title", "status", "generated_by", "published_at"]
    list_filter = ["status", "generated_by", "sponsor_type"]
    search_fields = ["title", "teaser"]
    readonly_fields = ["piece", "generated_by", "source_version", "published_at", "created_at", "updated_at"]


@admin.register(Leaf)
class LeafAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "kind", "visibility", "published_at", "is_reference"]
    list_filter = ["kind", "visibility"]


@admin.register(LeafComment)
class LeafCommentAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "placement", "is_approved", "is_flagged", "created_at"]
    list_filter = ["is_approved", "is_flagged"]
