from django.contrib import admin

from .models import (
    OcrSpikeArtifact,
    OcrSpikeEvaluation,
    OcrSpikeFeedbackNote,
    OcrSpikePage,
    OcrSpikeRecognitionAttempt,
)


@admin.register(OcrSpikeArtifact)
class OcrSpikeArtifactAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "status", "privacy_sensitivity", "page_count", "created_by", "created_at")
    list_filter = ("status", "privacy_sensitivity", "content_type")
    search_fields = ("original_filename", "source_file_path")


@admin.register(OcrSpikePage)
class OcrSpikePageAdmin(admin.ModelAdmin):
    list_display = ("artifact", "page_number", "preparation_status", "created_at")
    list_filter = ("preparation_status",)


@admin.register(OcrSpikeRecognitionAttempt)
class OcrSpikeRecognitionAttemptAdmin(admin.ModelAdmin):
    list_display = ("page", "provider", "engine_name", "status", "processing_time_ms", "created_at")
    list_filter = ("provider", "status", "engine_name")


@admin.register(OcrSpikeEvaluation)
class OcrSpikeEvaluationAdmin(admin.ModelAdmin):
    list_display = ("page", "outcome", "quality_rating", "correction_effort", "updated_at")
    list_filter = ("outcome", "correction_effort", "quality_rating")


@admin.register(OcrSpikeFeedbackNote)
class OcrSpikeFeedbackNoteAdmin(admin.ModelAdmin):
    list_display = ("screen", "artifact", "page", "created_by", "created_at")
    list_filter = ("screen",)
    search_fields = ("note",)
