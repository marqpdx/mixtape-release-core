from django.contrib import admin

from .models import Branch, LeafCluster, LivingBook


@admin.register(LivingBook)
class LivingBookAdmin(admin.ModelAdmin):
    list_display = ("title", "trunk", "status", "created_by", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "trunk__title")
    raw_id_fields = ("trunk", "created_by", "sponsor_content_type")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("id", "living_book", "anchor_node_id", "is_detached", "created_by", "created_at")
    list_filter = ("is_detached",)
    raw_id_fields = ("living_book", "created_by", "parent_branch")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(LeafCluster)
class LeafClusterAdmin(admin.ModelAdmin):
    list_display = ("id", "branch", "piece", "media_type", "created_by", "created_at")
    list_filter = ("media_type",)
    raw_id_fields = ("branch", "piece", "created_by")
    readonly_fields = ("id", "created_at", "updated_at")
