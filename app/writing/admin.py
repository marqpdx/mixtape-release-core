from django.contrib import admin

from writing.models import Leaf, LeafComment, WritingPiece, WritingWorkingCopy


@admin.register(WritingWorkingCopy)
class WorkingCopyAdmin(admin.ModelAdmin):
    list_display = ["id", "piece", "user", "last_saved_at"]


@admin.register(WritingPiece)
class WritingPieceAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "status", "writing_kind", "author"]


@admin.register(Leaf)
class LeafAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "kind", "visibility", "published_at", "is_reference"]
    list_filter = ["kind", "visibility"]


@admin.register(LeafComment)
class LeafCommentAdmin(admin.ModelAdmin):
    list_display = ["id", "author", "leaf", "is_approved", "is_flagged", "created_at"]
    list_filter = ["is_approved", "is_flagged"]
