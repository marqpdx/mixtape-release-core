from django.contrib import admin

from writing.models import (
    LeafComment,
    Seed,
    SeedDispatch,
    WorkingDocument,
    WritingPiece,
    WritingSeries,
    WritingSynopsis,
)


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


@admin.register(Seed)
class SeedAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "kind", "status", "updated_at", "promoted_to", "source"]
    list_filter = ["kind", "status", "source", "edited_after_transcription"]
    search_fields = ["id", "author__username", "author__email", "body_text", "transcript_text"]
    readonly_fields = [
        "id", "created_at", "updated_at", "body_hash", "transcript_hash", "transcript_created_at",
    ]
    raw_id_fields = ["author", "audio_file", "promoted_to"]


@admin.register(SeedDispatch)
class SeedDispatchAdmin(admin.ModelAdmin):
    list_display = ["id", "seed", "destination_type", "destination_id", "verb", "outcome", "dispatched_at"]
    list_filter = ["destination_type", "verb", "outcome"]
    raw_id_fields = ["seed"]


@admin.register(WritingSynopsis)
class WritingSynopsisAdmin(admin.ModelAdmin):
    list_display = ["id", "piece", "title", "status", "generated_by", "published_at"]
    list_filter = ["status", "generated_by", "sponsor_type"]
    search_fields = ["title", "teaser"]
    readonly_fields = ["piece", "generated_by", "source_version", "published_at", "created_at", "updated_at"]


@admin.register(LeafComment)
class LeafCommentAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "placement", "is_approved", "is_flagged", "created_at"]
    list_filter = ["is_approved", "is_flagged"]
